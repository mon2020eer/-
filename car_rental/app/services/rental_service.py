# -*- coding: utf-8 -*-
"""خدمة عقود الإيجار: فتح العقد وتعديله وتجديده وإغلاقه وإلغاؤه.

كل عملية هنا تمسّ أكثر من جدول (العقود + السيارات + الدفعات + سجلّ التدقيق)،
فتُنفَّذ داخل **معاملة واحدة**: إمّا أن تكتمل كلّها أو لا يُكتب منها شيء.

**الحجز المسبق:** السيارة الواحدة تحتمل عدّة عقود مفتوحة ما دامت فتراتها لا
تتداخل — فمكتب محدود عدد السيارات يحتاج أن يحجزها لعميل قادم قبل أن يُعيدها
العميل الحالي. الممنوع هو تأجيرها لعميلين في **الأيام نفسها**.

ثلاث طبقات تحمي من ذلك:
    1. فحص التداخل قبل الإدراج، برسالة عربية تسمّي العقد المتعارض.
    2. المعاملة الذرّية بـ ``BEGIN IMMEDIATE``.
    3. المشغّلان ``trg_contracts_no_overlap_*`` داخل قاعدة البيانات نفسها،
       وهما خطّ الدفاع الأخير الذي لا يمكن لأي كود تخطّيه.
"""

import datetime
import sqlite3

from ..core import audit, db, features, session
from ..repositories import contracts_repo, payments_repo, vehicles_repo
from . import pricing


class RentalError(Exception):
    """خطأ في منطق العقود برسالة عربية جاهزة للعرض."""


def _today():
    return datetime.date.today().isoformat()


def _assert_period_free(vehicle_id, start_date, end_date, exclude_contract_id=None, conn=None):
    """يرفع ``RentalError`` إن كانت السيارة محجوزة في أي يوم من الفترة المطلوبة."""
    clash = vehicles_repo.is_period_free(
        vehicle_id, start_date, end_date,
        exclude_contract_id=exclude_contract_id, conn=conn,
    )
    if clash is None:
        return None

    raise RentalError(
        "السيارة محجوزة في هذه الفترة ضمن العقد %s للعميل %s (من %s إلى %s).\n"
        "اختر فترة أخرى أو سيارة أخرى."
        % (clash["contract_number"], clash["customer_name"],
           clash["start_date"], clash["end_date"])
    )


def _wrap_overlap_error(error):
    """يحوّل رفض المشغّل في قاعدة البيانات إلى رسالة عربية مفهومة."""
    if "contract_period_overlap" in str(error):
        return RentalError("السيارة محجوزة في هذه الفترة ضمن عقد آخر.")
    return RentalError("تعذّر حفظ العقد: %s" % error)


def open_contract(customer_id, vehicle_id, start_date, expected_end_date,
                  discount=0, extra_charges=0, deposit_amount=0,
                  deposit_method="cash", pickup_location=None, notes=None,
                  start_odometer=None, start_time=None, conn=None):
    """يفتح عقد إيجار جديداً ويُرجع ``(معرّف العقد، رقم العقد)``.

    يحسب القيمة تلقائياً من تعرفة السيارة ومدّة الإيجار، ويحفظ لقطة من السعر
    وسعر الصرف داخل العقد، ثم يزامن حالة السيارة، ويسجّل العربون إن وُجد.

    العقد الذي يبدأ في تاريخ قادم **حجز**: يُقبل ولو كانت السيارة مؤجَّرة اليوم،
    وتبقى حالتها «مؤجَّرة» حتى ينتهي العقد الجاري ثم يبدأ الحجز في موعده.
    """
    user = session.require_login()
    features.require("contracts")

    customer = db.query_one(
        "SELECT * FROM customers WHERE id = ?", (customer_id,), conn=conn
    )
    if customer is None:
        raise RentalError("العميل غير موجود.")
    if customer["is_blacklisted"]:
        raise RentalError("هذا العميل مُدرج في القائمة السوداء، ولا يجوز التعاقد معه.")

    vehicle = db.query_one("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,), conn=conn)
    if vehicle is None:
        raise RentalError("السيارة غير موجودة.")
    if vehicle["status"] == "maintenance":
        raise RentalError("السيارة في الصيانة ولا يمكن تأجيرها.")

    currency = db.query_one(
        "SELECT * FROM currencies WHERE code = ?", (vehicle["currency_code"],), conn=conn
    )
    if currency is None:
        raise RentalError("عملة تعرفة السيارة غير معرَّفة في المنظومة.")

    try:
        estimate = pricing.quote(
            start_date, expected_end_date,
            vehicle["daily_rate"], vehicle["weekly_rate"],
            discount, extra_charges,
        )
    except ValueError as error:
        raise RentalError(str(error))

    deposit_amount = max(0, int(deposit_amount or 0))
    if deposit_amount > estimate["total"]:
        raise RentalError("قيمة العربون تتجاوز إجمالي العقد.")

    start_iso = pricing.parse_date(start_date).isoformat()
    end_iso = pricing.parse_date(expected_end_date).isoformat()
    start_time = pricing.parse_time(start_time).strftime("%H:%M")

    _assert_period_free(vehicle_id, start_iso, end_iso, conn=conn)

    hourly_rate = int(vehicle["hourly_rate"] or 0) or pricing.default_hourly_rate(
        vehicle["daily_rate"]
    )

    try:
        with db.transaction(conn) as tx:
            contract_number = contracts_repo.next_contract_number(conn=tx)

            cursor = tx.execute(
                """INSERT INTO contracts (
                        contract_number, customer_id, vehicle_id,
                        start_date, expected_end_date, start_time,
                        daily_rate_snapshot, weekly_rate_snapshot, hourly_rate_snapshot,
                        currency_code, rate_to_base,
                        days_count, subtotal, discount, extra_charges, total_amount,
                        start_odometer, pickup_location, notes, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    contract_number, customer_id, vehicle_id,
                    start_iso, end_iso, start_time,
                    vehicle["daily_rate"], vehicle["weekly_rate"], hourly_rate,
                    currency["code"], currency["rate_to_base"],
                    estimate["days"], estimate["subtotal"], estimate["discount"],
                    estimate["extra_charges"], estimate["total"],
                    start_odometer if start_odometer is not None else vehicle["odometer"],
                    pickup_location, notes, user.id,
                ),
            )
            contract_id = cursor.lastrowid

            vehicles_repo.sync_status(vehicle_id, conn=tx)

            if deposit_amount:
                tx.execute(
                    """INSERT INTO payments (contract_id, amount, method, kind, recorded_by)
                       VALUES (?, ?, ?, 'deposit', ?)""",
                    (contract_id, deposit_amount, deposit_method, user.id),
                )

            audit.log(
                "create", "contract", contract_id,
                {
                    "number": contract_number,
                    "vehicle": vehicle["plate_number"],
                    "customer": customer["full_name"],
                    "period": "%s → %s" % (start_iso, end_iso),
                    "total": estimate["total"],
                },
                conn=tx,
            )

    except sqlite3.IntegrityError as error:
        # خطّ الدفاع الأخير: مشغّل منع التداخل داخل قاعدة البيانات
        raise _wrap_overlap_error(error)

    return contract_id, contract_number


def close_contract(contract_id, actual_end_date=None, extra_charges=0,
                   end_odometer=None, return_location=None, note=None,
                   actual_end_time=None, hourly=False, conn=None):
    """يُغلق عقداً مفتوحاً ويعيد حساب القيمة بالمدّة الفعلية.

    ``hourly=True`` يحتسب المدّة بالساعات لا بالأيام، وهو المطلوب عند الإرجاع
    المبكّر: من أعاد السيارة قبل الموعد بخمس ساعات لا يَعدل أن يُحاسَب بيوم كامل.

    يُرجع قاموس التسوية: القيمة الجديدة والفرق عن القيمة الأصلية والمتبقّي.
    """
    user = session.require_login()

    contract = contracts_repo.get_raw(contract_id, conn=conn)
    if contract is None:
        raise RentalError("العقد غير موجود.")
    if contract["status"] != "open":
        raise RentalError("هذا العقد غير مفتوح أصلاً.")

    if hourly:
        features.require("hourly_billing")

    actual_end_date = actual_end_date or _today()
    end_time = pricing.parse_time(actual_end_time).strftime("%H:%M") if hourly else None

    try:
        result = pricing.settlement(
            contract, actual_end_date, extra_charges,
            actual_end_time=end_time, hourly=hourly,
        )
    except ValueError as error:
        raise RentalError(str(error))

    paid = int(payments_repo.balance(contract_id, conn=conn)["paid_amount"])
    if result["total"] < paid:
        raise RentalError(
            "القيمة النهائية للعقد أقلّ ممّا دفعه العميل. سجّل مبلغاً مُعاداً أولاً."
        )

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE contracts
                  SET status = 'closed',
                      actual_end_date = ?, actual_end_time = ?,
                      billing_mode = ?, hours_count = ?,
                      days_count = ?, subtotal = ?,
                      extra_charges = ?, total_amount = ?,
                      end_odometer = COALESCE(?, end_odometer),
                      return_location = COALESCE(?, return_location),
                      notes = CASE WHEN ? IS NULL THEN notes
                                   ELSE COALESCE(notes || char(10), '') || ? END,
                      closed_by = ?, closed_at = datetime('now', 'localtime')
                WHERE id = ?""",
            (
                pricing.parse_date(actual_end_date).isoformat(), end_time,
                result["mode"], result.get("hours", 0),
                result["days"], result["subtotal"], result["extra_charges"],
                result["total"], end_odometer, return_location, note, note,
                user.id, contract_id,
            ),
        )

        if end_odometer is not None:
            tx.execute(
                "UPDATE vehicles SET odometer = ? WHERE id = ? AND ? > odometer",
                (end_odometer, contract["vehicle_id"], end_odometer),
            )

        # الحالة تُشتقّ: قد يكون للسيارة حجز قادم أو عقد آخر سارٍ اليوم
        vehicles_repo.sync_status(contract["vehicle_id"], conn=tx)

        audit.log(
            "close", "contract", contract_id,
            {"total": result["total"], "difference": result["difference"],
             "mode": result["mode"], "hours": result.get("hours")}, conn=tx,
        )

    result["paid_amount"] = paid
    result["balance_due"] = result["total"] - paid
    return result


def update_contract(contract_id, start_date=None, expected_end_date=None,
                    vehicle_id=None, discount=None, extra_charges=None,
                    notes=None, pickup_location=None, start_time=None, conn=None):
    """يعدّل عقداً مفتوحاً ويعيد حساب قيمته.

    يسمح بتصحيح التواريخ والخصم والرسوم، **وبتبديل السيارة** — وهو أمر يقع فعلاً
    في المكاتب حين تتعطّل السيارة المتفَّق عليها فتُستبدل بأخرى.

    يرفض ما يُفسد السجلّ: فترة متداخلة مع عقد آخر، أو قيمة نهائية أقلّ ممّا دفعه
    العميل بالفعل.
    """
    session.require_login()

    contract = contracts_repo.get_raw(contract_id, conn=conn)
    if contract is None:
        raise RentalError("العقد غير موجود.")
    if contract["status"] != "open":
        raise RentalError("لا يمكن تعديل عقد غير مفتوح.")

    old_vehicle_id = contract["vehicle_id"]
    new_vehicle_id = vehicle_id or old_vehicle_id

    vehicle = db.query_one(
        "SELECT * FROM vehicles WHERE id = ?", (new_vehicle_id,), conn=conn
    )
    if vehicle is None:
        raise RentalError("السيارة غير موجودة.")
    if new_vehicle_id != old_vehicle_id and vehicle["status"] == "maintenance":
        raise RentalError("السيارة البديلة في الصيانة.")

    start_iso = pricing.parse_date(start_date or contract["start_date"]).isoformat()
    end_iso = pricing.parse_date(
        expected_end_date or contract["expected_end_date"]
    ).isoformat()
    if end_iso < start_iso:
        raise RentalError("تاريخ نهاية العقد يسبق تاريخ بدايته.")

    _assert_period_free(new_vehicle_id, start_iso, end_iso,
                        exclude_contract_id=contract_id, conn=conn)

    # تبديل السيارة يعني تعرفة جديدة، وبقاؤها يعني الاحتفاظ باللقطة الأصلية
    if new_vehicle_id != old_vehicle_id:
        daily = vehicle["daily_rate"]
        weekly = vehicle["weekly_rate"]
        hourly = int(vehicle["hourly_rate"] or 0) or pricing.default_hourly_rate(daily)
        currency = db.query_one(
            "SELECT * FROM currencies WHERE code = ?", (vehicle["currency_code"],), conn=conn
        )
    else:
        daily = contract["daily_rate_snapshot"]
        weekly = contract["weekly_rate_snapshot"]
        hourly = contract["hourly_rate_snapshot"]
        currency = None

    estimate = pricing.quote(
        start_iso, end_iso, daily, weekly,
        contract["discount"] if discount is None else discount,
        contract["extra_charges"] if extra_charges is None else extra_charges,
    )

    paid = int(payments_repo.balance(contract_id, conn=conn)["paid_amount"])
    if estimate["total"] < paid:
        raise RentalError(
            "القيمة الجديدة (%d) أقلّ ممّا دفعه العميل بالفعل. سجّل مبلغاً مُعاداً أولاً."
            % estimate["total"]
        )

    try:
        with db.transaction(conn) as tx:
            tx.execute(
                """UPDATE contracts
                      SET vehicle_id = ?, start_date = ?, expected_end_date = ?,
                          start_time = COALESCE(?, start_time),
                          daily_rate_snapshot = ?, weekly_rate_snapshot = ?,
                          hourly_rate_snapshot = ?,
                          currency_code = COALESCE(?, currency_code),
                          rate_to_base = COALESCE(?, rate_to_base),
                          days_count = ?, subtotal = ?, discount = ?,
                          extra_charges = ?, total_amount = ?,
                          pickup_location = COALESCE(?, pickup_location),
                          notes = COALESCE(?, notes)
                    WHERE id = ?""",
                (
                    new_vehicle_id, start_iso, end_iso,
                    pricing.parse_time(start_time).strftime("%H:%M") if start_time else None,
                    daily, weekly, hourly,
                    currency["code"] if currency else None,
                    currency["rate_to_base"] if currency else None,
                    estimate["days"], estimate["subtotal"], estimate["discount"],
                    estimate["extra_charges"], estimate["total"],
                    pickup_location, notes, contract_id,
                ),
            )

            vehicles_repo.sync_status(new_vehicle_id, conn=tx)
            if new_vehicle_id != old_vehicle_id:
                vehicles_repo.sync_status(old_vehicle_id, conn=tx)

            audit.log(
                "update", "contract", contract_id,
                {"period": "%s → %s" % (start_iso, end_iso),
                 "vehicle_id": new_vehicle_id, "total": estimate["total"]},
                conn=tx,
            )
    except sqlite3.IntegrityError as error:
        raise _wrap_overlap_error(error)

    return estimate


def renew_contract(contract_id, days=None, expected_end_date=None,
                   deposit_amount=0, deposit_method="cash", conn=None):
    """يجدّد عقداً: ينشئ عقداً **جديداً** لنفس العميل ونفس السيارة يبدأ من انتهاء الحالي.

    التجديد ليس تمديداً: التمديد يمدّ العقد القائم ويُبقي رقمه، أمّا التجديد فيُنشئ
    عقداً مستقلاً برقم جديد — وهو ما يناسب العميل الذي أنهى مدّته ثم قرّر الاستمرار،
    فيبقى لكل مدّة عقدها وسجلّ دفعاتها.
    """
    session.require_login()

    contract = contracts_repo.get_raw(contract_id, conn=conn)
    if contract is None:
        raise RentalError("العقد غير موجود.")

    start = pricing.parse_date(
        contract["actual_end_date"] or contract["expected_end_date"]
    )
    if expected_end_date is None:
        expected_end_date = start + datetime.timedelta(days=max(1, int(days or 7)))

    return open_contract(
        customer_id=contract["customer_id"],
        vehicle_id=contract["vehicle_id"],
        start_date=start,
        expected_end_date=expected_end_date,
        deposit_amount=deposit_amount,
        deposit_method=deposit_method,
        start_time=contract["start_time"],
        notes="تجديد للعقد %s" % contract["contract_number"],
        conn=conn,
    )


@session.requires_role("admin")
def cancel_contract(contract_id, reason=None, conn=None):
    """يلغي عقداً — للمدير فقط.

    الإلغاء لا يمحو العقد ولا دفعاته، بل ينقله إلى حالة «مُلغى» ويحرّر السيارة،
    فيبقى أثر العملية كاملاً في السجلّات.
    """
    contract = contracts_repo.get_raw(contract_id, conn=conn)
    if contract is None:
        raise RentalError("العقد غير موجود.")
    if contract["status"] == "cancelled":
        raise RentalError("العقد مُلغى بالفعل.")

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE contracts
                  SET status = 'cancelled', closed_by = ?,
                      closed_at = datetime('now', 'localtime'),
                      notes = CASE WHEN ? IS NULL THEN notes
                                   ELSE COALESCE(notes || char(10), '') || 'سبب الإلغاء: ' || ? END
                WHERE id = ?""",
            (session.current_user_id(), reason, reason, contract_id),
        )
        tx.execute(
            """UPDATE vehicles SET status = 'available'
                WHERE id = ? AND status = 'rented'""",
            (contract["vehicle_id"],),
        )
        audit.log("cancel", "contract", contract_id, {"reason": reason}, conn=tx)

    return True


def extend_contract(contract_id, new_expected_end_date, conn=None):
    """يمدّد عقداً مفتوحاً ويعيد حساب قيمته بالمدّة الجديدة."""
    session.require_login()

    contract = contracts_repo.get_raw(contract_id, conn=conn)
    if contract is None:
        raise RentalError("العقد غير موجود.")
    if contract["status"] != "open":
        raise RentalError("لا يمكن تمديد عقد غير مفتوح.")

    new_end = pricing.parse_date(new_expected_end_date)
    if new_end <= pricing.parse_date(contract["expected_end_date"]):
        raise RentalError("تاريخ التمديد يجب أن يتجاوز تاريخ الانتهاء الحالي.")

    estimate = pricing.quote(
        contract["start_date"], new_end,
        contract["daily_rate_snapshot"], contract["weekly_rate_snapshot"],
        contract["discount"], contract["extra_charges"],
    )

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE contracts
                  SET expected_end_date = ?, days_count = ?, subtotal = ?, total_amount = ?
                WHERE id = ?""",
            (new_end.isoformat(), estimate["days"], estimate["subtotal"],
             estimate["total"], contract_id),
        )
        audit.log(
            "update", "contract", contract_id,
            {"extended_to": new_end.isoformat(), "total": estimate["total"]}, conn=tx,
        )

    return estimate

# -*- coding: utf-8 -*-
"""خدمة عقود الإيجار: فتح العقد وإغلاقه وإلغاؤه.

كل عملية هنا تمسّ أكثر من جدول (العقود + السيارات + الدفعات + سجلّ التدقيق)،
فتُنفَّذ داخل **معاملة واحدة**: إمّا أن تكتمل كلّها أو لا يُكتب منها شيء.
الحالة الوسطى — عقد مسجَّل وسيارة ما زالت «متاحة» — كارثة تشغيلية لأنّها
تسمح بتأجير السيارة نفسها مرّتين.

ثلاث طبقات تحمي من الحجز المزدوج:
    1. التحقّق من حالة السيارة قبل الإدراج.
    2. المعاملة الذرّية بـ ``BEGIN IMMEDIATE``.
    3. الفهرس الفريد الجزئي ``ux_vehicle_open_contract`` في قاعدة البيانات
       نفسها، وهو خطّ الدفاع الأخير الذي لا يمكن لأي كود تخطّيه.
"""

import datetime
import sqlite3

from ..core import audit, db, session
from ..repositories import contracts_repo, payments_repo
from . import pricing


class RentalError(Exception):
    """خطأ في منطق العقود برسالة عربية جاهزة للعرض."""


def _today():
    return datetime.date.today().isoformat()


def open_contract(customer_id, vehicle_id, start_date, expected_end_date,
                  discount=0, extra_charges=0, deposit_amount=0,
                  deposit_method="cash", pickup_location=None, notes=None,
                  start_odometer=None, conn=None):
    """يفتح عقد إيجار جديداً ويُرجع ``(معرّف العقد، رقم العقد)``.

    يحسب القيمة تلقائياً من تعرفة السيارة ومدّة الإيجار، ويحفظ لقطة من السعر
    وسعر الصرف داخل العقد، ثم ينقل السيارة إلى حالة «مؤجَّرة»، ويسجّل العربون
    إن وُجد.
    """
    user = session.require_login()

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
    if vehicle["status"] == "rented":
        raise RentalError("السيارة مؤجَّرة حالياً ضمن عقد مفتوح.")
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

    try:
        with db.transaction(conn) as tx:
            contract_number = contracts_repo.next_contract_number(conn=tx)

            cursor = tx.execute(
                """INSERT INTO contracts (
                        contract_number, customer_id, vehicle_id,
                        start_date, expected_end_date,
                        daily_rate_snapshot, weekly_rate_snapshot,
                        currency_code, rate_to_base,
                        days_count, subtotal, discount, extra_charges, total_amount,
                        start_odometer, pickup_location, notes, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    contract_number, customer_id, vehicle_id,
                    pricing.parse_date(start_date).isoformat(),
                    pricing.parse_date(expected_end_date).isoformat(),
                    vehicle["daily_rate"], vehicle["weekly_rate"],
                    currency["code"], currency["rate_to_base"],
                    estimate["days"], estimate["subtotal"], estimate["discount"],
                    estimate["extra_charges"], estimate["total"],
                    start_odometer if start_odometer is not None else vehicle["odometer"],
                    pickup_location, notes, user.id,
                ),
            )
            contract_id = cursor.lastrowid

            tx.execute("UPDATE vehicles SET status = 'rented' WHERE id = ?", (vehicle_id,))

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
                    "total": estimate["total"],
                },
                conn=tx,
            )

    except sqlite3.IntegrityError as error:
        # خطّ الدفاع الأخير: الفهرس الفريد الجزئي رفض عقداً مفتوحاً ثانياً
        if "ux_vehicle_open_contract" in str(error):
            raise RentalError("هذه السيارة مرتبطة بعقد مفتوح بالفعل.")
        raise RentalError("تعذّر حفظ العقد: %s" % error)

    return contract_id, contract_number


def close_contract(contract_id, actual_end_date=None, extra_charges=0,
                   end_odometer=None, return_location=None, note=None, conn=None):
    """يُغلق عقداً مفتوحاً ويعيد حساب القيمة بالمدّة الفعلية.

    يُرجع قاموس التسوية: القيمة الجديدة والفرق عن القيمة الأصلية والمتبقّي.
    """
    user = session.require_login()

    contract = contracts_repo.get_raw(contract_id, conn=conn)
    if contract is None:
        raise RentalError("العقد غير موجود.")
    if contract["status"] != "open":
        raise RentalError("هذا العقد غير مفتوح أصلاً.")

    actual_end_date = actual_end_date or _today()

    try:
        result = pricing.settlement(contract, actual_end_date, extra_charges)
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
                      actual_end_date = ?, days_count = ?, subtotal = ?,
                      extra_charges = ?, total_amount = ?,
                      end_odometer = COALESCE(?, end_odometer),
                      return_location = COALESCE(?, return_location),
                      notes = CASE WHEN ? IS NULL THEN notes
                                   ELSE COALESCE(notes || char(10), '') || ? END,
                      closed_by = ?, closed_at = datetime('now', 'localtime')
                WHERE id = ?""",
            (
                pricing.parse_date(actual_end_date).isoformat(),
                result["days"], result["subtotal"], result["extra_charges"],
                result["total"], end_odometer, return_location, note, note,
                user.id, contract_id,
            ),
        )

        tx.execute(
            "UPDATE vehicles SET status = 'available' WHERE id = ?",
            (contract["vehicle_id"],),
        )

        if end_odometer is not None:
            tx.execute(
                "UPDATE vehicles SET odometer = ? WHERE id = ? AND ? > odometer",
                (end_odometer, contract["vehicle_id"], end_odometer),
            )

        audit.log(
            "close", "contract", contract_id,
            {"total": result["total"], "difference": result["difference"]}, conn=tx,
        )

    result["paid_amount"] = paid
    result["balance_due"] = result["total"] - paid
    return result


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

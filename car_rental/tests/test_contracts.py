# -*- coding: utf-8 -*-
"""اختبارات تكامل العقود: الحجز المزدوج، الدفعات، الإغلاق، التقارير."""

import datetime
import sqlite3

import pytest

from app.core import db, session
from app.repositories import contracts_repo, payments_repo, vehicles_repo
from app.services import rental_service


def _dates(days=3):
    today = datetime.date.today()
    return today.isoformat(), (today + datetime.timedelta(days=days)).isoformat()


def test_open_contract_marks_vehicle_rented(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(3)
    contract_id, number = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )

    assert number.startswith("CR-")
    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "rented"

    contract = contracts_repo.get(contract_id, conn=conn)
    assert contract["days_count"] == 3
    assert contract["total_amount"] == 3 * 15000     # 3 أيام × 150.00
    assert contract["payment_status"] == "due"


def test_overlapping_period_is_refused(conn, admin, sample_customer, sample_vehicle):
    """التداخل في الأيام نفسها مرفوض، والرسالة تسمّي العقد المتعارض."""
    start, end = _dates(5)
    rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)

    overlap_start = (datetime.date.fromisoformat(start)
                     + datetime.timedelta(days=2)).isoformat()
    overlap_end = (datetime.date.fromisoformat(start)
                   + datetime.timedelta(days=9)).isoformat()

    with pytest.raises(rental_service.RentalError) as error:
        rental_service.open_contract(
            sample_customer, sample_vehicle, overlap_start, overlap_end, conn=conn
        )

    message = str(error.value)
    assert "محجوزة" in message
    assert "CR-" in message                      # تسمية العقد المتعارض
    assert "محمد علي الشريف" in message          # وصاحبه


def test_advance_reservation_is_accepted(conn, admin, sample_customer, sample_vehicle):
    """جوهر التغيير: السيارة المؤجَّرة اليوم تُحجَز لفترة لاحقة لا تتداخل.

    مكتب محدود عدد السيارات يحتاج هذا فعلاً، ولا خطأ فيه: العميلان لا يستعملان
    السيارة في اليوم نفسه.
    """
    today = datetime.date.today()
    rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=3)).isoformat(), conn=conn,
    )

    second_id, second_number = rental_service.open_contract(
        sample_customer, sample_vehicle,
        (today + datetime.timedelta(days=5)).isoformat(),
        (today + datetime.timedelta(days=9)).isoformat(),
        conn=conn,
    )

    assert second_id
    # عقدان مفتوحان على السيارة نفسها: ما كان ممكناً قبل هذا التغيير
    open_count = conn.execute(
        "SELECT COUNT(*) FROM contracts WHERE vehicle_id = ? AND status = 'open'",
        (sample_vehicle,),
    ).fetchone()[0]
    assert open_count == 2

    # والسيارة تبقى «مؤجَّرة» لأن العقد الجاري اليوم هو الأول، لا الحجز القادم
    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "rented"
    assert len(vehicles_repo.upcoming_reservations(sample_vehicle, conn=conn)) == 1
    assert second_number.startswith("CR-")


def test_handover_day_is_shared(conn, admin, sample_customer, sample_vehicle):
    """يوم التسليم يصلح بدايةً لعقد تالٍ: من يُعيدها يوم 5 تُسلَّم لغيره يوم 5."""
    today = datetime.date.today()
    handover = (today + datetime.timedelta(days=3)).isoformat()

    rental_service.open_contract(
        sample_customer, sample_vehicle, today.isoformat(), handover, conn=conn
    )
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, handover,
        (today + datetime.timedelta(days=6)).isoformat(), conn=conn,
    )
    assert contract_id


def test_database_trigger_blocks_overlap_even_bypassing_service(
    conn, admin, sample_customer, sample_vehicle
):
    """خطّ الدفاع الأخير: مشغّل منع التداخل داخل قاعدة البيانات نفسها.

    نتجاوز طبقة الخدمة عمداً ونُدرج عقداً متداخلاً مباشرةً بـ SQL،
    ويجب أن ترفضه قاعدة البيانات.
    """
    start, end = _dates(4)
    rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)

    with pytest.raises(sqlite3.IntegrityError) as error:
        conn.execute(
            """INSERT INTO contracts (
                    contract_number, customer_id, vehicle_id, start_date,
                    expected_end_date, daily_rate_snapshot, currency_code,
                    rate_to_base, days_count, subtotal, total_amount, created_by)
               VALUES ('CR-BYPASS', ?, ?, ?, ?, 1000, 'LYD', 1000000, 1, 1000, 1000, ?)""",
            (sample_customer, sample_vehicle, start, end, admin.id),
        )
    assert "contract_period_overlap" in str(error.value)


def test_trigger_allows_non_overlapping_raw_insert(
    conn, admin, sample_customer, sample_vehicle
):
    """المشغّل يمنع التداخل فقط، ولا يمنع الحجز المتتابع."""
    today = datetime.date.today()
    rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
    )

    conn.execute(
        """INSERT INTO contracts (
                contract_number, customer_id, vehicle_id, start_date,
                expected_end_date, daily_rate_snapshot, currency_code,
                rate_to_base, days_count, subtotal, total_amount, created_by)
           VALUES ('CR-RAW-OK', ?, ?, ?, ?, 1000, 'LYD', 1000000, 1, 1000, 1000, ?)""",
        (sample_customer, sample_vehicle,
         (today + datetime.timedelta(days=10)).isoformat(),
         (today + datetime.timedelta(days=12)).isoformat(), admin.id),
    )
    assert contracts_repo.get_by_number("CR-RAW-OK", conn=conn) is not None


def test_status_follows_the_calendar_not_the_contract_count(
    conn, admin, sample_customer, sample_vehicle
):
    """حجز قادم وحده لا يجعل السيارة مؤجَّرة اليوم."""
    today = datetime.date.today()
    rental_service.open_contract(
        sample_customer, sample_vehicle,
        (today + datetime.timedelta(days=4)).isoformat(),
        (today + datetime.timedelta(days=8)).isoformat(),
        conn=conn,
    )
    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "available"


def test_update_contract_recalculates_and_checks_overlap(
    conn, admin, sample_customer, sample_vehicle
):
    """تعديل العقد يعيد الحساب، ويرفض التعديل الذي يصطدم بحجز قائم."""
    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
    )
    # حجز قادم يبدأ بعد 5 أيام
    rental_service.open_contract(
        sample_customer, sample_vehicle,
        (today + datetime.timedelta(days=5)).isoformat(),
        (today + datetime.timedelta(days=8)).isoformat(), conn=conn,
    )

    # تمديد العقد الأول إلى 4 أيام: لا يصطدم بشيء
    estimate = rental_service.update_contract(
        contract_id,
        expected_end_date=(today + datetime.timedelta(days=4)).isoformat(),
        conn=conn,
    )
    assert estimate["days"] == 4
    assert contracts_repo.get(contract_id, conn=conn)["days_count"] == 4

    # تمديده إلى ما بعد بداية الحجز القادم: مرفوض
    with pytest.raises(rental_service.RentalError):
        rental_service.update_contract(
            contract_id,
            expected_end_date=(today + datetime.timedelta(days=7)).isoformat(),
            conn=conn,
        )


def test_update_contract_can_swap_vehicle(conn, admin, sample_customer, sample_vehicle):
    """تبديل السيارة في عقد قائم يزامن حالتَي السيارتين ويأخذ التعرفة الجديدة."""
    replacement = vehicles_repo.create(
        {
            "brand": "مازدا", "model": "6", "year": 2022, "plate_number": "8-24680",
            "color": "رمادي", "daily_rate": 20000, "weekly_rate": 0,
            "currency_code": "LYD",
        },
        conn=conn,
    )

    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
    )

    rental_service.update_contract(contract_id, vehicle_id=replacement, conn=conn)

    contract = contracts_repo.get_raw(contract_id, conn=conn)
    assert contract["vehicle_id"] == replacement
    assert contract["daily_rate_snapshot"] == 20000
    assert contract["total_amount"] == 2 * 20000
    assert vehicles_repo.get(replacement, conn=conn)["status"] == "rented"
    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "available"


def test_update_contract_cannot_drop_below_paid(
    conn, admin, sample_customer, sample_vehicle
):
    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=5)).isoformat(),
        deposit_amount=60000, conn=conn,
    )

    with pytest.raises(rental_service.RentalError) as error:
        rental_service.update_contract(
            contract_id,
            expected_end_date=(today + datetime.timedelta(days=1)).isoformat(),
            conn=conn,
        )
    assert "دفعه العميل" in str(error.value)


def test_renew_contract_creates_a_new_following_contract(
    conn, admin, sample_customer, sample_vehicle
):
    """التجديد ينشئ عقداً جديداً يبدأ من انتهاء الحالي، بلا تداخل."""
    today = datetime.date.today()
    first_id, first_number = rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=3)).isoformat(), conn=conn,
    )

    second_id, second_number = rental_service.renew_contract(first_id, days=4, conn=conn)

    assert second_id != first_id
    assert second_number != first_number

    renewed = contracts_repo.get_raw(second_id, conn=conn)
    assert renewed["start_date"] == (today + datetime.timedelta(days=3)).isoformat()
    assert renewed["days_count"] == 4
    assert first_number in (renewed["notes"] or "")


def test_maintenance_vehicle_cannot_be_rented(conn, admin, sample_customer, sample_vehicle):
    from app.repositories import maintenance_repo

    maintenance_repo.open_maintenance(sample_vehicle, "تغيير الفرامل", conn=conn)
    start, end = _dates(2)

    with pytest.raises(rental_service.RentalError) as error:
        rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)
    assert "الصيانة" in str(error.value)


def test_blacklisted_customer_cannot_rent(conn, admin, sample_customer, sample_vehicle):
    conn.execute("UPDATE customers SET is_blacklisted = 1 WHERE id = ?", (sample_customer,))
    start, end = _dates(2)

    with pytest.raises(rental_service.RentalError) as error:
        rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)
    assert "السوداء" in str(error.value)


def test_deposit_is_recorded_as_payment(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(4)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, deposit_amount=20000, conn=conn
    )

    contract = contracts_repo.get(contract_id, conn=conn)
    assert contract["paid_amount"] == 20000
    assert contract["payment_status"] == "deposit"
    assert contract["balance_due"] == contract["total_amount"] - 20000


def test_partial_payments_accumulate(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    total = contracts_repo.get(contract_id, conn=conn)["total_amount"]

    payments_repo.add(contract_id, total // 2, conn=conn)
    middle = contracts_repo.get(contract_id, conn=conn)
    assert middle["payment_status"] == "deposit"

    payments_repo.add(contract_id, total - total // 2, conn=conn)
    final = contracts_repo.get(contract_id, conn=conn)
    assert final["payment_status"] == "paid"
    assert final["balance_due"] == 0


def test_overpayment_is_refused(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    total = contracts_repo.get(contract_id, conn=conn)["total_amount"]

    with pytest.raises(ValueError):
        payments_repo.add(contract_id, total + 1, conn=conn)


def test_close_contract_frees_vehicle_and_resettles(conn, admin, sample_customer, sample_vehicle):
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=5)).isoformat()
    expected = (today - datetime.timedelta(days=2)).isoformat()

    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, expected, conn=conn
    )
    before = contracts_repo.get(contract_id, conn=conn)["total_amount"]

    # أُعيدت متأخّرة يومين عن الموعد المتوقَّع
    result = rental_service.close_contract(contract_id, today.isoformat(), conn=conn)

    assert result["days"] == 5
    assert result["total"] > before                      # التأخير زاد القيمة
    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "available"
    assert contracts_repo.get_raw(contract_id, conn=conn)["status"] == "closed"


def test_close_contract_by_the_hour_on_early_return(
    conn, admin, sample_customer, sample_vehicle
):
    """الإرجاع المبكّر يُحتسب بالساعة لا بيوم كامل.

    السيناريو الواقعي: عقد ثلاثة أيام، والعميل أعادها في اليوم الثاني ظهراً —
    أي بعد 26 ساعة: يوم كامل وساعتان، لا ثلاثة أيام ولا يومان كاملان.
    """
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=1)).isoformat()

    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        start, (today + datetime.timedelta(days=2)).isoformat(),
        start_time="10:00", conn=conn,
    )
    before = contracts_repo.get(contract_id, conn=conn)["total_amount"]

    result = rental_service.close_contract(
        contract_id, actual_end_date=today.isoformat(),
        actual_end_time="12:00", hourly=True, conn=conn,
    )

    assert result["mode"] == "hourly"
    assert result["hours"] == 26                 # 24 + 2
    assert result["full_days"] == 1
    assert result["remainder_hours"] == 2
    # يوم كامل (15000) + ساعتان بسعر الساعة (ceil(15000/24)=625 × 2)
    assert result["total"] == 15000 + 2 * 625
    assert result["total"] < before

    closed = contracts_repo.get_raw(contract_id, conn=conn)
    assert closed["billing_mode"] == "hourly"
    assert closed["hours_count"] == 26
    assert closed["actual_end_time"] == "12:00"


def test_hourly_close_never_exceeds_a_full_day(conn, admin, sample_customer):
    """سقف الإنصاف بالساعة: ساعات الكسر لا تُكلّف أكثر من يوم كامل.

    السيارة هنا لها سعر ساعة صريح مرتفع (2000 والسعر اليومي 15000)، فلولا السقف
    لصارت 15 ساعة (30000) أغلى من يومين كاملين.
    """
    vehicle = vehicles_repo.create(
        {
            "brand": "لكزس", "model": "ES", "year": 2024, "plate_number": "1-10101",
            "color": "أبيض", "daily_rate": 15000, "weekly_rate": 0,
            "hourly_rate": 2000, "currency_code": "LYD",
        },
        conn=conn,
    )

    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, vehicle,
        today.isoformat(), (today + datetime.timedelta(days=3)).isoformat(),
        start_time="08:00", conn=conn,
    )

    result = rental_service.close_contract(
        contract_id, actual_end_date=today.isoformat(),
        actual_end_time="23:00", hourly=True, conn=conn,
    )
    assert result["hours"] == 15
    assert result["total"] == 15000              # سعر يوم واحد، لا 30000


def test_daily_close_is_still_the_default(conn, admin, sample_customer, sample_vehicle):
    """الإغلاق المعتاد يبقى باليوم ما لم يُطلب غير ذلك."""
    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        (today - datetime.timedelta(days=2)).isoformat(),
        (today + datetime.timedelta(days=1)).isoformat(), conn=conn,
    )

    result = rental_service.close_contract(
        contract_id, actual_end_date=today.isoformat(), conn=conn
    )
    assert result["mode"] == "daily"
    assert result["days"] == 2
    assert contracts_repo.get_raw(contract_id, conn=conn)["billing_mode"] == "daily"


def test_closed_vehicle_can_be_rented_again(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(1)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    rental_service.close_contract(contract_id, end, conn=conn)

    second_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, end, end, conn=conn
    )
    assert second_id != contract_id


def test_cancel_contract_frees_vehicle_and_keeps_record(
    conn, admin, sample_customer, sample_vehicle
):
    start, end = _dates(3)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )

    rental_service.cancel_contract(contract_id, reason="طلب العميل", conn=conn)

    assert contracts_repo.get_raw(contract_id, conn=conn)["status"] == "cancelled"
    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "available"


def test_extend_contract_recalculates_total(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )

    new_end = (datetime.date.fromisoformat(end) + datetime.timedelta(days=3)).isoformat()
    estimate = rental_service.extend_contract(contract_id, new_end, conn=conn)

    assert estimate["days"] == 5
    assert contracts_repo.get(contract_id, conn=conn)["days_count"] == 5


def test_staff_cannot_cancel_contract(conn, admin, sample_customer, sample_vehicle):
    from app.repositories import users_repo

    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )

    users_repo.create("nour", "نور الموظّفة", "Sayara2026", "staff", conn=conn)
    users_repo.authenticate("nour", "Sayara2026", conn=conn)

    with pytest.raises(session.PermissionDenied):
        rental_service.cancel_contract(contract_id, conn=conn)


def test_contract_numbers_increment(conn, admin, sample_customer, sample_vehicle):
    from app.repositories import vehicles_repo as repo

    second_vehicle = repo.create(
        {
            "brand": "هيونداي", "model": "النترا", "year": 2021,
            "plate_number": "7-99999", "color": "أسود",
            "daily_rate": 12000, "weekly_rate": 0, "currency_code": "LYD",
        },
        conn=conn,
    )

    start, end = _dates(1)
    _, first_number = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    _, second_number = rental_service.open_contract(
        sample_customer, second_vehicle, start, end, conn=conn
    )

    assert int(first_number.rsplit("-", 1)[1]) + 1 == int(second_number.rsplit("-", 1)[1])


def test_dashboard_summary_reflects_state(conn, admin, sample_customer, sample_vehicle):
    from app.services import reporting

    start, end = _dates(3)
    rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, deposit_amount=10000, conn=conn
    )

    summary = reporting.dashboard_summary(conn=conn)
    assert summary["fleet"]["rented"] == 1
    assert summary["fleet"]["available"] == 0
    assert summary["contracts"]["open"] == 1
    assert summary["outstanding"] > 0
    assert summary["occupancy"] == 100.0


def test_audit_log_records_operations(conn, admin, sample_customer, sample_vehicle):
    from app.core import audit

    start, end = _dates(2)
    rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)

    actions = {row["action"] for row in audit.recent(conn=conn)}
    assert "login" in actions
    assert "create" in actions


def test_vehicle_with_contracts_cannot_be_deleted(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(1)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    rental_service.close_contract(contract_id, end, conn=conn)

    with pytest.raises(ValueError):
        vehicles_repo.delete(sample_vehicle, conn=conn)


def test_multi_currency_reporting_uses_contract_rate(conn, admin, sample_customer):
    """عقد بالدولار يُجمَّع في التقارير بسعر الصرف المحفوظ في العقد."""
    from app.repositories import settings_repo
    from app.services import reporting

    usd_vehicle = vehicles_repo.create(
        {
            "brand": "نيسان", "model": "صني", "year": 2023,
            "plate_number": "9-11111", "color": "فضّي",
            "daily_rate": 10000, "weekly_rate": 0, "currency_code": "USD",
        },
        conn=conn,
    )

    start, end = _dates(1)
    rental_service.open_contract(sample_customer, usd_vehicle, start, end, conn=conn)

    # سعر الصرف الافتراضي 5.5 دينار للدولار ← 100 دولار = 550 ديناراً
    report = reporting.revenue_report(start, end, conn=conn)
    assert report["contracted"] == 55000

    # تعديل سعر الصرف لاحقاً لا يغيّر تقرير العقد القديم
    settings_repo.set_exchange_rate("USD", 9.0, conn=conn)
    assert reporting.revenue_report(start, end, conn=conn)["contracted"] == 55000


# ---------------------------------------------------------------------------
# مزامنة حالة السيارة: الحالة تُشتقّ من العقود لا تُفرض إدخالاً
# ---------------------------------------------------------------------------
def test_cancelling_a_future_booking_keeps_the_rented_vehicle_rented(
    conn, admin, sample_customer, sample_vehicle
):
    """إلغاء حجز قادم لا يجوز أن يُحرّر سيارةً في يد عميل اليوم.

    السيارة الواحدة تحمل عقداً جارياً وحجوزات قادمة معاً منذ أُتيح الحجز
    المسبق. فإن حرّر إلغاءُ الحجز السيارةَ، عرضتها المنظومة «متاحة» وهي
    مؤجَّرة فعلاً — وهذا طريق التأجير المزدوج.
    """
    today = datetime.date.today()
    rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=2)).isoformat(),
        conn=conn,
    )
    booking_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        (today + datetime.timedelta(days=5)).isoformat(),
        (today + datetime.timedelta(days=7)).isoformat(),
        conn=conn,
    )

    rental_service.cancel_contract(booking_id, reason="اعتذر العميل", conn=conn)

    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "rented"


def test_cancelling_the_only_contract_frees_the_vehicle(
    conn, admin, sample_customer, sample_vehicle
):
    """وفي المقابل: إلغاء العقد الوحيد يُرجع السيارة متاحة كما ينبغي."""
    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )

    rental_service.cancel_contract(contract_id, conn=conn)

    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "available"


def test_extending_a_contract_resynchronizes_vehicle_status(
    conn, admin, sample_customer, sample_vehicle
):
    """التمديد يعيد اشتقاق حالة السيارة بدل أن يتركها على حالها القديم.

    الحالة تنحرف بمرور الوقت وحده — حجز الغد يصير إيجار اليوم والتطبيق مغلق —
    فكل عملية تمسّ مدّة العقد موضعُ إعادة اشتقاق.
    """
    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    db.execute(
        "UPDATE vehicles SET status = 'available' WHERE id = ?",
        (sample_vehicle,), conn=conn,
    )

    rental_service.extend_contract(
        contract_id,
        (datetime.date.today() + datetime.timedelta(days=6)).isoformat(),
        conn=conn,
    )

    assert vehicles_repo.get(sample_vehicle, conn=conn)["status"] == "rented"


# ---------------------------------------------------------------------------
# المستحقّات: من عقود الفترة نفسها لا من طرح دفعات فترة أخرى
# ---------------------------------------------------------------------------
def test_outstanding_counts_only_the_period_contracts(
    conn, admin, sample_customer, sample_vehicle
):
    """دفعة داخل الفترة على عقد أقدم لا تُنقص مستحقّات الفترة.

    ‹المستحقّات› جواب سؤال «كم لي عند الناس من عقود هذا الشهر؟» — وطرحُ
    مقبوضات الشهر من تعاقداته يخلط مجموعتين مختلفتين، فيخرج رقم لا يصف شيئاً.
    """
    from app.services import reporting

    today = datetime.date.today()
    old_start = today - datetime.timedelta(days=40)
    old_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        old_start.isoformat(), (old_start + datetime.timedelta(days=2)).isoformat(),
        conn=conn,
    )
    rental_service.close_contract(
        old_id, (old_start + datetime.timedelta(days=2)).isoformat(), conn=conn
    )

    period_start = (today - datetime.timedelta(days=3)).isoformat()
    new_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle,
        period_start, (today + datetime.timedelta(days=1)).isoformat(),
        conn=conn,
    )
    period_total = contracts_repo.get(new_id, conn=conn)["total_amount"]

    # سداد العقد القديم اليوم — داخل فترة التقرير، وخارج عقودها
    payments_repo.add(old_id, 10000, conn=conn)

    report = reporting.revenue_report(
        period_start, (today + datetime.timedelta(days=1)).isoformat(), conn=conn
    )
    assert report["outstanding"] == period_total


def test_outstanding_drops_when_the_period_contract_is_paid(
    conn, admin, sample_customer, sample_vehicle
):
    """وتسديدُ عقد الفترة يُنقص مستحقّاتها — وإلّا لم يكن الرقم يقيس شيئاً."""
    from app.services import reporting

    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )
    total = contracts_repo.get(contract_id, conn=conn)["total_amount"]
    payments_repo.add(contract_id, 10000, conn=conn)

    assert reporting.revenue_report(start, end, conn=conn)["outstanding"] == total - 10000


# ---------------------------------------------------------------------------
# فحص الرصيد تحت قفل الكتابة
# ---------------------------------------------------------------------------
def test_payment_balance_check_runs_inside_the_write_transaction(
    conn, admin, sample_customer, sample_vehicle, monkeypatch
):
    """التحقّق من المتبقّي يجري داخل المعاملة لا قبلها.

    لو جرى قبلها لمرّ اتّصالان من الفحص نفسه ثم أدرجا دفعتين متعاقبتين،
    فتجاوز المدفوع قيمة العقد رغم أن كليهما ‹تحقّق›.
    """
    start, end = _dates(2)
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, start, end, conn=conn
    )

    seen = {}
    original = payments_repo.balance

    def spy(contract, conn=None):
        seen["locked"] = bool(conn is not None and conn.in_transaction)
        return original(contract, conn=conn)

    monkeypatch.setattr(payments_repo, "balance", spy)
    payments_repo.add(contract_id, 5000, conn=conn)

    assert seen.get("locked") is True

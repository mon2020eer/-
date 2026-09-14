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


def test_double_booking_is_refused(conn, admin, sample_customer, sample_vehicle):
    start, end = _dates(2)
    rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)

    with pytest.raises(rental_service.RentalError) as error:
        rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)
    assert "مؤجَّرة" in str(error.value)


def test_database_index_blocks_double_booking_even_bypassing_service(
    conn, admin, sample_customer, sample_vehicle
):
    """خطّ الدفاع الأخير: الفهرس الفريد الجزئي في قاعدة البيانات نفسها.

    نتجاوز طبقة الخدمة عمداً ونُدرج عقداً مفتوحاً ثانياً مباشرةً بـ SQL،
    ويجب أن ترفضه قاعدة البيانات.
    """
    start, end = _dates(2)
    rental_service.open_contract(sample_customer, sample_vehicle, start, end, conn=conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO contracts (
                    contract_number, customer_id, vehicle_id, start_date,
                    expected_end_date, daily_rate_snapshot, currency_code,
                    rate_to_base, days_count, subtotal, total_amount, created_by)
               VALUES ('CR-BYPASS', ?, ?, ?, ?, 1000, 'LYD', 1000000, 1, 1000, 1000, ?)""",
            (sample_customer, sample_vehicle, start, end, admin.id),
        )


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

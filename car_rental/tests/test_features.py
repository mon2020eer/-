# -*- coding: utf-8 -*-
"""اختبارات مزايا النسختين ووضع القفل.

المقصد الأهمّ: أن يكون المنع في **طبقة الخدمة** لا في إخفاء أزرار الواجهة.
فالاختبارات تستدعي الخدمات مباشرةً متجاوزةً الواجهة كلّها.
"""

import datetime

import pytest

from app.core import features
from app.repositories import customers_repo, maintenance_repo, users_repo, vehicles_repo
from app.services import rental_service, reporting


@pytest.fixture()
def basic(conn, admin):
    """النسخة الأساسية فعّالة أثناء الاختبار، ثم تُعاد المتقدّمة."""
    features.set_tier(features.TIER_BASIC)
    yield
    features.set_tier(features.TIER_PRO)


@pytest.fixture()
def locked(conn, admin):
    """وضع القفل (اشتراك منتهٍ)."""
    features.set_tier(features.TIER_LOCKED)
    yield
    features.set_tier(features.TIER_PRO)


def _vehicle_data(plate, **extra):
    data = {
        "brand": "تويوتا", "model": "ياريس", "year": 2023, "plate_number": plate,
        "color": "أبيض", "daily_rate": 10000, "weekly_rate": 0, "currency_code": "LYD",
    }
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# خريطة المزايا
# ---------------------------------------------------------------------------
def test_basic_covers_the_daily_work():
    """الأساسية ليست منتجاً معطوباً: عمل المكتب اليومي كامل فيها."""
    for name in ("vehicles", "customers", "contracts", "payments",
                 "contract_pdf", "dashboard", "local_backup"):
        assert features.has_feature(name, features.TIER_BASIC), name


def test_basic_excludes_premium_features():
    for name in ("reports", "export", "cloud_backup", "maintenance",
                 "hourly_billing", "multi_currency", "multi_user", "audit_log"):
        assert not features.has_feature(name, features.TIER_BASIC), name


def test_pro_has_everything():
    assert not features.missing_features(features.TIER_PRO)
    assert features.missing_features(features.TIER_BASIC)


def test_locked_allows_reading_and_backup_only():
    """وضع القفل لا يحجب بيانات المكتب عن صاحبه، بل يمنع العمل الجديد."""
    assert features.has_feature("local_backup", features.TIER_LOCKED)
    assert features.has_feature("contract_pdf", features.TIER_LOCKED)
    assert not features.has_feature("contracts", features.TIER_LOCKED)
    assert not features.has_feature("payments", features.TIER_LOCKED)


# ---------------------------------------------------------------------------
# المنع في طبقة الخدمة
# ---------------------------------------------------------------------------
def test_basic_cannot_open_reports(conn, admin, basic):
    with pytest.raises(features.FeatureLocked) as error:
        reporting.revenue_report("2026-01-01", "2026-12-31", conn=conn)
    assert "المتقدّمة" in str(error.value)


def test_basic_cannot_export(conn, admin, basic, tmp_path):
    with pytest.raises(features.FeatureLocked):
        reporting.export_rows_to_csv([], [("a", "أ")], tmp_path / "x.csv")


def test_basic_cannot_use_cloud_backup(conn, admin, basic):
    from app.services.backup import backup_service

    with pytest.raises(features.FeatureLocked):
        backup_service.run_backup(mode="manual")


def test_basic_can_still_take_a_local_backup(conn, admin, basic):
    """النسخة الأساسية تحمي بيانات صاحبها ولو بلا سحابة."""
    from app.services.backup import backup_service

    archive = backup_service.create_local_snapshot()
    assert archive.exists()


def test_basic_cannot_record_maintenance(conn, admin, basic):
    vehicle = vehicles_repo.create(_vehicle_data("1-11111"), conn=conn)
    with pytest.raises(features.FeatureLocked):
        maintenance_repo.open_maintenance(vehicle, "تغيير زيت", conn=conn)


def test_basic_cannot_add_a_second_user(conn, admin, basic):
    with pytest.raises(features.FeatureLocked):
        users_repo.create("staff9", "موظّف", "Sayara2026", "staff", conn=conn)


def test_basic_cannot_close_by_the_hour(conn, admin, basic):
    customer = customers_repo.create(
        {"full_name": "عميل", "phone": "091", "national_id": "H1",
         "license_number": "LC-H1"}, conn=conn,
    )
    vehicle = vehicles_repo.create(_vehicle_data("2-22222"), conn=conn)
    today = datetime.date.today()

    contract_id, _ = rental_service.open_contract(
        customer, vehicle, today.isoformat(),
        (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
    )

    with pytest.raises(features.FeatureLocked):
        rental_service.close_contract(
            contract_id, actual_end_date=today.isoformat(),
            actual_end_time="14:00", hourly=True, conn=conn,
        )

    # والإغلاق العادي باليوم يعمل في الأساسية
    result = rental_service.close_contract(
        contract_id, actual_end_date=today.isoformat(), conn=conn
    )
    assert result["mode"] == "daily"


def test_basic_enforces_the_vehicle_limit(conn, admin, basic):
    """الحدّ يُفرض في المستودع لا في الواجهة، فلا يُتجاوز بأي طريق."""
    for index in range(features.BASIC_VEHICLE_LIMIT):
        vehicles_repo.create(_vehicle_data("L-%05d" % index), conn=conn)

    with pytest.raises(features.FeatureLocked) as error:
        vehicles_repo.create(_vehicle_data("L-OVER"), conn=conn)
    assert str(features.BASIC_VEHICLE_LIMIT) in str(error.value)


def test_pro_has_no_vehicle_limit(conn, admin):
    assert features.vehicle_limit(features.TIER_PRO) == 0
    for index in range(features.BASIC_VEHICLE_LIMIT + 3):
        vehicles_repo.create(_vehicle_data("P-%05d" % index), conn=conn)
    assert len(vehicles_repo.search(limit=100, conn=conn)) > features.BASIC_VEHICLE_LIMIT


# ---------------------------------------------------------------------------
# وضع القفل
# ---------------------------------------------------------------------------
def test_locked_blocks_new_work(conn, admin, locked):
    with pytest.raises(features.FeatureLocked) as error:
        customers_repo.create(
            {"full_name": "عميل", "phone": "091", "national_id": "X9",
             "license_number": "LC-X9"}, conn=conn,
        )
    assert "انتهى اشتراكك" in str(error.value)

    with pytest.raises(features.FeatureLocked):
        vehicles_repo.create(_vehicle_data("9-99999"), conn=conn)


def test_locked_keeps_the_office_data_reachable(conn, admin, locked):
    """لا يُحجب عن صاحب المكتب بياناته ولا نسخته الاحتياطية."""
    from app.services.backup import backup_service

    assert customers_repo.search(conn=conn) is not None
    archive = backup_service.create_local_snapshot()
    assert archive.exists()


def test_locked_blocks_new_contracts(conn, admin):
    customer = customers_repo.create(
        {"full_name": "عميل مقفل", "phone": "092", "national_id": "L1",
         "license_number": "LC-L1"}, conn=conn,
    )
    vehicle = vehicles_repo.create(_vehicle_data("3-33333"), conn=conn)

    features.set_tier(features.TIER_LOCKED)
    try:
        today = datetime.date.today()
        with pytest.raises(features.FeatureLocked):
            rental_service.open_contract(
                customer, vehicle, today.isoformat(),
                (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
            )
    finally:
        features.set_tier(features.TIER_PRO)


def test_unknown_tier_is_refused():
    with pytest.raises(ValueError):
        features.set_tier("gold")
    assert features.current_tier() == features.TIER_PRO

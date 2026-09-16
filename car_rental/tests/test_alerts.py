# -*- coding: utf-8 -*-
"""اختبارات محرّك التنبيهات: ما انتهى وما يوشك وما لا يستحقّ إزعاجاً."""

import datetime

import pytest

from app.core import features
from app.repositories import customers_repo, vehicles_repo
from app.services import alerts

TODAY = datetime.date(2026, 6, 1)


def _vehicle(conn, plate, **extra):
    data = {
        "brand": "تويوتا", "model": "كورولا", "year": 2022, "plate_number": plate,
        "color": "أبيض", "daily_rate": 15000, "weekly_rate": 0, "currency_code": "LYD",
    }
    data.update(extra)
    return vehicles_repo.create(data, conn=conn)


def _date(days_from_today):
    return (TODAY + datetime.timedelta(days=days_from_today)).isoformat()


# ---------------------------------------------------------------------------
# التصنيف
# ---------------------------------------------------------------------------
def test_expired_soon_and_safe_are_sorted_into_their_boxes(conn, admin):
    _vehicle(conn, "1-00001", insurance_expiry=_date(-10))    # منتهٍ
    _vehicle(conn, "2-00002", insurance_expiry=_date(5))      # يوشك
    _vehicle(conn, "3-00003", insurance_expiry=_date(200))    # سليم

    found = alerts.collect(today=TODAY, threshold=30, conn=conn)
    by_severity = {alert.severity for alert in found}

    assert len(found) == 2, "السليم لا يُنتج تنبيهاً"
    assert by_severity == {alerts.EXPIRED, alerts.SOON}


def test_expired_comes_before_soon(conn, admin):
    """ترتيب الإلحاح ليس تجميلاً: أوّل سطر يقرؤه صاحب المكتب أخطرُها."""
    _vehicle(conn, "1-11111", insurance_expiry=_date(3))
    _vehicle(conn, "2-22222", insurance_expiry=_date(-40))

    found = alerts.collect(today=TODAY, conn=conn)
    assert found[0].severity == alerts.EXPIRED


def test_threshold_is_respected(conn, admin):
    _vehicle(conn, "1-11111", insurance_expiry=_date(20))

    assert alerts.collect(today=TODAY, threshold=30, conn=conn)
    assert not alerts.collect(today=TODAY, threshold=7, conn=conn)


def test_missing_or_broken_dates_produce_nothing(conn, admin):
    """سيارة بلا تاريخ تأمين ليست سيارة بتأمين منتهٍ."""
    _vehicle(conn, "1-11111")                                   # بلا تاريخ
    _vehicle(conn, "2-22222", insurance_expiry="")              # فارغ
    _vehicle(conn, "3-33333", insurance_expiry="غير تاريخ")     # مشوّه

    assert alerts.collect(today=TODAY, conn=conn) == []


# ---------------------------------------------------------------------------
# المصادر الثلاثة
# ---------------------------------------------------------------------------
def test_all_three_sources_are_covered(conn, admin):
    _vehicle(conn, "1-11111", insurance_expiry=_date(-1))
    _vehicle(conn, "2-22222", inspection_expiry=_date(-1))
    customers_repo.create(
        {"full_name": "عميل برخصة منتهية", "license_expiry": _date(-1)}, conn=conn
    )

    kinds = {alert.kind for alert in alerts.collect(today=TODAY, conn=conn)}
    assert kinds == {"insurance", "inspection", "license"}


def test_kinds_filter_narrows_the_list(conn, admin):
    _vehicle(conn, "1-11111", insurance_expiry=_date(-1), inspection_expiry=_date(-1))

    found = alerts.collect(today=TODAY, kinds=["insurance"], conn=conn)
    assert [alert.kind for alert in found] == ["insurance"]


def test_blacklisted_customers_are_skipped(conn, admin):
    """عميل ممنوع من التعاقد لا تُهمّ صلاحية رخصته."""
    customers_repo.create(
        {"full_name": "ممنوع", "license_expiry": _date(-1), "is_blacklisted": 1},
        conn=conn,
    )
    assert alerts.collect(today=TODAY, kinds=["license"], conn=conn) == []


# ---------------------------------------------------------------------------
# الرسائل والملخّص
# ---------------------------------------------------------------------------
def test_message_counts_in_correct_arabic(conn, admin):
    _vehicle(conn, "1-11111", insurance_expiry=_date(1))
    _vehicle(conn, "2-22222", insurance_expiry=_date(5))

    messages = [alert.message for alert in alerts.collect(today=TODAY, conn=conn)]
    assert any("يوم واحد" in text for text in messages)     # لا «1 يوم»
    assert any("5 أيام" in text for text in messages)


def test_summary_counts_match_the_list(conn, admin):
    _vehicle(conn, "1-11111", insurance_expiry=_date(-1))
    _vehicle(conn, "2-22222", insurance_expiry=_date(2))

    counts = alerts.summary(today=TODAY, conn=conn)
    assert counts == {"total": 2, "expired": 1, "soon": 1}


# ---------------------------------------------------------------------------
# تأمين سيارة بعينها عند فتح العقد
# ---------------------------------------------------------------------------
def test_vehicle_insurance_state_flags_only_the_expired(conn, admin):
    expired = vehicles_repo.get(
        _vehicle(conn, "1-11111", insurance_expiry=_date(-1)), conn=conn
    )
    valid = vehicles_repo.get(
        _vehicle(conn, "2-22222", insurance_expiry=_date(1)), conn=conn
    )
    unknown = vehicles_repo.get(_vehicle(conn, "3-33333"), conn=conn)

    assert alerts.vehicle_insurance_state(expired, today=TODAY) is not None
    assert alerts.vehicle_insurance_state(valid, today=TODAY) is None
    assert alerts.vehicle_insurance_state(unknown, today=TODAY) is None


# ---------------------------------------------------------------------------
# النسخة
# ---------------------------------------------------------------------------
def test_basic_tier_cannot_use_alerts(conn, admin):
    features.set_tier(features.TIER_BASIC)
    try:
        with pytest.raises(features.FeatureLocked):
            alerts.collect(today=TODAY, conn=conn)
    finally:
        features.set_tier(features.TIER_PRO)

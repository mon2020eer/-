# -*- coding: utf-8 -*-
"""اختبارات محرّك التسعير — وحدة صافية لا تحتاج قاعدة بيانات."""

import pytest

from app.services import pricing

DAILY = 10000    # 100.00
WEEKLY = 60000   # 600.00


def test_minimum_one_day():
    """الاستلام والتسليم في اليوم نفسه يُحتسب يوماً كاملاً."""
    assert pricing.rental_days("2026-03-01", "2026-03-01") == 1


def test_plain_day_count():
    assert pricing.rental_days("2026-03-01", "2026-03-06") == 5


def test_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        pricing.rental_days("2026-03-10", "2026-03-01")


def test_daily_only_when_no_weekly_rate():
    assert pricing.base_amount(9, DAILY, 0) == 9 * DAILY


def test_exact_week_uses_weekly_rate():
    assert pricing.base_amount(7, DAILY, WEEKLY) == WEEKLY


def test_week_plus_remainder():
    """9 أيام = أسبوع (600) + يومان (200) = 800."""
    assert pricing.base_amount(9, DAILY, WEEKLY) == WEEKLY + 2 * DAILY


def test_fairness_cap_six_days_never_costs_more_than_a_week():
    """ستة أيام بالسعر اليومي (600) تُقارن بأسبوع كامل (600) فتؤخذ الأرخص."""
    six_days = pricing.base_amount(6, DAILY, WEEKLY)
    full_week = pricing.base_amount(7, DAILY, WEEKLY)
    assert six_days <= full_week


def test_fairness_cap_applies_to_expensive_remainder():
    """13 يوماً: أسبوع + 6 أيام (1200) أغلى من أسبوعين (1200) — فلا يتجاوزهما."""
    assert pricing.base_amount(13, DAILY, WEEKLY) <= 2 * WEEKLY


def test_quote_applies_discount_and_extras():
    result = pricing.quote("2026-03-01", "2026-03-08", DAILY, WEEKLY,
                           discount=5000, extra_charges=2000)
    assert result["days"] == 7
    assert result["subtotal"] == WEEKLY
    assert result["total"] == WEEKLY - 5000 + 2000


def test_discount_cannot_exceed_subtotal():
    """خصم أكبر من قيمة الإيجار يُقصّ عند القيمة، فلا يصير الإجمالي سالباً."""
    result = pricing.quote("2026-03-01", "2026-03-03", DAILY, 0, discount=10 ** 9)
    assert result["discount"] == result["subtotal"]
    assert result["total"] == 0


def test_settlement_detects_late_return():
    contract = {
        "start_date": "2026-03-01",
        "daily_rate_snapshot": DAILY,
        "weekly_rate_snapshot": 0,
        "discount": 0,
        "extra_charges": 0,
        "total_amount": 3 * DAILY,
    }
    result = pricing.settlement(contract, "2026-03-05")
    assert result["days"] == 4
    assert result["difference"] == DAILY  # يوم تأخير واحد


# ---------------------------------------------------------------------------
# الاحتساب بالساعة
# ---------------------------------------------------------------------------
HOURLY = 1000


def _at(day, hour):
    import datetime

    return datetime.datetime(2026, 3, day, hour, 0)


def test_default_hourly_rate_rounds_up():
    """التقريب لأعلى مقصود: لولاه لصارت 24 ساعة أرخص من يوم كامل."""
    assert pricing.default_hourly_rate(10000) == 417      # ceil(10000/24)
    assert pricing.default_hourly_rate(417 * 24) >= 417
    assert pricing.default_hourly_rate(0) == 0


def test_minimum_one_hour():
    """من استلم السيارة وأعادها بعد نصف ساعة يدفع ساعة."""
    assert pricing.rental_hours(_at(1, 10), _at(1, 10)) == 1


def test_partial_hour_counts_as_full_hour():
    import datetime

    start = _at(1, 10)
    assert pricing.rental_hours(start, start + datetime.timedelta(minutes=70)) == 2


def test_hours_reject_reversed_times():
    with pytest.raises(ValueError):
        pricing.rental_hours(_at(2, 10), _at(1, 10))


def test_five_hours_are_billed_hourly():
    assert pricing.base_amount_hours(5, DAILY, 0, HOURLY) == 5 * HOURLY


def test_hourly_total_is_capped_at_the_daily_rate():
    """سقف الإنصاف: 15 ساعة × 1000 = 15000، لكنّها لا تتجاوز سعر اليوم 10000."""
    assert pricing.base_amount_hours(15, DAILY, 0, HOURLY) == DAILY


def test_exact_day_uses_the_daily_rate():
    assert pricing.base_amount_hours(24, DAILY, 0, HOURLY) == DAILY


def test_day_plus_hours():
    """27 ساعة = يوم كامل + 3 ساعات."""
    assert pricing.base_amount_hours(27, DAILY, 0, HOURLY) == DAILY + 3 * HOURLY


def test_hourly_respects_the_weekly_rate_for_full_days():
    """الأيام الكاملة تمرّ على قاعدة الأسبوع، والساعات تُضاف بعدها."""
    hours = 7 * 24 + 2
    assert pricing.base_amount_hours(hours, DAILY, WEEKLY, HOURLY) == WEEKLY + 2 * HOURLY


def test_quote_hours_reports_the_breakdown():
    result = pricing.quote_hours(_at(1, 8), _at(2, 13), DAILY, 0, HOURLY)
    assert result["hours"] == 29
    assert result["full_days"] == 1
    assert result["remainder_hours"] == 5
    assert result["total"] == DAILY + 5 * HOURLY


def test_settlement_hourly_on_early_return():
    """التسوية بالساعة عند الإرجاع المبكّر تنقص القيمة عن العقد الأصلي."""
    contract = {
        "start_date": "2026-03-01",
        "start_time": "10:00",
        "daily_rate_snapshot": DAILY,
        "weekly_rate_snapshot": 0,
        "hourly_rate_snapshot": HOURLY,
        "discount": 0,
        "extra_charges": 0,
        "total_amount": 3 * DAILY,
    }
    result = pricing.settlement(contract, "2026-03-02", actual_end_time="14:00", hourly=True)

    assert result["mode"] == "hourly"
    assert result["hours"] == 28
    assert result["total"] == DAILY + 4 * HOURLY
    assert result["difference"] < 0                 # أقلّ من قيمة العقد الأصلية


def test_describe_duration_uses_correct_arabic_plurals():
    """العربية تميّز المفرد والمثنّى وجمعَي القلّة والكثرة، و«6 ساعة» ركيك."""
    assert pricing.describe_duration(1) == "ساعة واحدة"
    assert pricing.describe_duration(2) == "ساعتان"
    assert pricing.describe_duration(5) == "5 ساعات"
    assert pricing.describe_duration(11) == "11 ساعة"
    assert pricing.describe_duration(24) == "يوم واحد"
    assert pricing.describe_duration(30) == "يوم واحد و6 ساعات"
    assert pricing.describe_duration(48) == "يومان"
    assert pricing.describe_duration(72) == "3 أيام"
    assert pricing.describe_duration(26 * 24) == "26 يوماً"


def test_settlement_detects_early_return():
    contract = {
        "start_date": "2026-03-01",
        "daily_rate_snapshot": DAILY,
        "weekly_rate_snapshot": 0,
        "discount": 0,
        "extra_charges": 0,
        "total_amount": 5 * DAILY,
    }
    result = pricing.settlement(contract, "2026-03-03")
    assert result["days"] == 2
    assert result["difference"] == -3 * DAILY

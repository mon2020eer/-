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

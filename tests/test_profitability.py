# -*- coding: utf-8 -*-
"""اختبارات وحدة تحليل ربحية السيارات وعائد الاستثمار.

ثلاث مجموعات:
    • **الترقية**: تُضاف الأعمدة والجدول الجديد إلى قاعدة مكتبٍ عامل بلا فقد صفّ.
    • **المعادلة**: الإيراد والتكلفة والصافي ونسبة الاسترداد، وما يُستثنى منها.
    • **المستودع**: ما يُقبل من مدخلات وما يُرفض، ومن يملك الحذف.
"""

import datetime
import sqlite3

import pytest

from app.core import db, features, money, session
from app.repositories import expenses_repo, maintenance_repo, vehicles_repo
from app.services import profitability

TODAY = datetime.date.today()


def _days_ago(count):
    return (TODAY - datetime.timedelta(days=count)).isoformat()


@pytest.fixture()
def vehicle_with_price(admin, conn):
    """سيارة بتكلفة شراء مسجَّلة: 20,000.00 اشتُريت قبل عشرة أشهر."""
    return vehicles_repo.create(
        {
            "brand": "نيسان",
            "model": "صني",
            "year": 2018,
            "plate_number": "7-70000",
            "color": "أزرق",
            "daily_rate": 10000,
            "currency_code": "LYD",
            "purchase_price": 2_000_000,
            "purchase_date": (TODAY - datetime.timedelta(days=300)).isoformat(),
        },
        conn=conn,
    )


def _rent(customer_id, vehicle_id, start_days_ago, days, conn):
    """يفتح عقداً منتهياً في الماضي ويُرجع معرّفه وقيمته."""
    from app.services import rental_service

    start = TODAY - datetime.timedelta(days=start_days_ago)
    end = start + datetime.timedelta(days=days)
    contract_id, _ = rental_service.open_contract(
        customer_id, vehicle_id, start.isoformat(), end.isoformat(), conn=conn
    )
    return contract_id


# ---------------------------------------------------------------------------
# الترقية ٥: الأعمدة والجدول الجديد
# ---------------------------------------------------------------------------
def test_purchase_columns_exist(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(vehicles)")}
    assert "purchase_price" in columns
    assert "purchase_date" in columns


def test_expenses_table_and_views_exist(conn):
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "vehicle_expenses" in tables

    views = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view'"
    )}
    assert "v_vehicle_expense_ledger" in views
    assert "v_vehicle_profitability" in views


def test_purchase_price_starts_unknown_not_zero(sample_vehicle, conn):
    """سيارة سُجّلت بلا ثمن تبقى ``NULL``: «لا نعرف» ليست «كلّفت صفراً»."""
    row = vehicles_repo.get(sample_vehicle, conn=conn)
    assert row["purchase_price"] is None

    report = profitability.vehicle_profitability(sample_vehicle, conn=conn)
    assert report["has_purchase_price"] is False
    assert report["recovery_ratio"] is None      # لا نسبة بلا مقام


def test_upgrading_an_old_database_keeps_every_row(app_home):
    """قاعدة مكتبٍ عامل تُرقَّى فتُضاف الأعمدة ولا يضيع صفّ واحد.

    هذا هو الوعد الذي يُسلَّم مع التحديث: الترقية تضيف ولا تحذف.
    """
    from app import config
    from tests.test_migrations import _build_v1_database

    _build_v1_database(config.DB_PATH)
    connection = db.initialize()

    assert connection.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1
    assert connection.execute(
        "SELECT contract_number FROM contracts"
    ).fetchone()[0] == "CR-2025-0001"

    columns = {row[1] for row in connection.execute("PRAGMA table_info(vehicles)")}
    assert {"purchase_price", "purchase_date"} <= columns

    # والسيارة القديمة تدخل التقرير فوراً بثمن شراء غير مسجَّل
    row = connection.execute("SELECT * FROM v_vehicle_profitability").fetchone()
    assert row["has_purchase_price"] == 0
    assert row["total_revenue"] == 45000
    db.close_connection()


# ---------------------------------------------------------------------------
# معادلة الربحية
# ---------------------------------------------------------------------------
def test_revenue_counts_contracts_and_excludes_cancelled(
    admin, conn, sample_customer, vehicle_with_price
):
    """العقد الملغى لا يُنتج ديناراً، فلا يدخل الإيراد."""
    from app.services import rental_service

    _rent(sample_customer, vehicle_with_price, 60, 4, conn)      # 4 × 100.00
    cancelled = _rent(sample_customer, vehicle_with_price, 30, 3, conn)
    rental_service.cancel_contract(cancelled, conn=conn)

    report = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert report["contracts_count"] == 1
    assert report["total_revenue"] == 40000
    assert report["net_profit"] == 40000


def test_expenses_are_summed_from_the_ledger(admin, conn, vehicle_with_price):
    expenses_repo.add_expense(vehicle_with_price, "tyres", 90000,
                              date=_days_ago(20), conn=conn)
    expenses_repo.add_expense(vehicle_with_price, "oil", 12000, conn=conn)

    report = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert report["total_expenses"] == 102000
    assert report["net_profit"] == -102000


def test_maintenance_costs_are_counted_too(admin, conn, vehicle_with_price):
    """تكلفة الورشة المسجَّلة في شاشة الصيانة جزء من تكلفة السيارة.

    لولا ذلك لظهرت سيارةٌ أنفق المكتب على إصلاحها آلافاً وكأنّها بلا تكلفة —
    وهو خطأ أسوأ من غياب التقرير كلّه، لأنّه خطأ **يُطمأنّ إليه**.
    """
    maintenance_repo.open_maintenance(
        vehicle_with_price, "تغيير ناقل الحركة", cost=250000, conn=conn
    )
    expenses_repo.add_expense(vehicle_with_price, "oil", 12000, conn=conn)

    report = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert report["total_expenses"] == 262000

    sources = {row["source"] for row in expenses_repo.list_ledger(vehicle_with_price,
                                                                 conn=conn)}
    assert sources == {"expense", "maintenance"}


def test_money_pit_is_detected_and_flagged(
    admin, conn, sample_customer, vehicle_with_price
):
    """السيارة التي تجاوزت تكاليفُها إيرادَها تُصنَّف «حفرة مال»."""
    _rent(sample_customer, vehicle_with_price, 40, 2, conn)       # إيراد 200.00
    expenses_repo.add_expense(vehicle_with_price, "maintenance", 350000,
                              date=_days_ago(10), conn=conn)

    report = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert report["total_expenses"] > report["total_revenue"]
    assert report["profit_status"] == profitability.STATUS_MONEY_PIT
    assert report["is_money_pit"] is True
    assert report["net_profit"] < 0


def test_recovery_ratio_measures_capital_returned(
    admin, conn, sample_customer, vehicle_with_price
):
    """نسبة الاسترداد = صافي الربح ÷ تكلفة الشراء.

    تُقاس بالصافي لا بالإيراد: إيرادٌ يلتهمه الإصلاح لا يستردّ من رأس المال شيئاً.
    """
    _rent(sample_customer, vehicle_with_price, 90, 60, conn)      # 60 × 100.00
    expenses_repo.add_expense(vehicle_with_price, "tyres", 100000, conn=conn)

    report = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert report["total_revenue"] == 600000
    assert report["net_profit"] == 500000
    assert report["recovery_ratio"] == 25.0                      # 500000 / 2000000
    assert report["remaining_to_recover"] == 1_500_000


def test_status_bands_follow_the_capital_recovered():
    """الحالات الأربع تُشتقّ من الأرقام لا من تقدير الواجهة."""
    assert profitability.classify(-1, 1000) == profitability.STATUS_MONEY_PIT
    assert profitability.classify(500, 1000) == profitability.STATUS_RECOVERING
    assert profitability.classify(1000, 1000) == profitability.STATUS_PROFITABLE
    assert profitability.classify(0, 0, has_activity=False) == profitability.STATUS_IDLE

    # بلا ثمن شراء مسجَّل: الحكم بالربح التشغيلي وحده
    assert profitability.classify(
        500, 0, has_purchase_price=False
    ) == profitability.STATUS_PROFITABLE


def test_a_vehicle_with_no_activity_is_not_called_profitable(sample_vehicle, conn, admin):
    """صفرٌ في الطرفين ليس ربحاً، وتلوينه أخضر يمنح طمأنينة بلا مقابل."""
    report = profitability.vehicle_profitability(sample_vehicle, conn=conn)
    assert report["profit_status"] == profitability.STATUS_IDLE


def test_fleet_report_puts_the_worst_first(
    admin, conn, sample_customer, sample_vehicle, vehicle_with_price
):
    _rent(sample_customer, sample_vehicle, 50, 10, conn)          # سيارة رابحة
    expenses_repo.add_expense(vehicle_with_price, "maintenance", 500000, conn=conn)

    rows = profitability.fleet_profitability(conn=conn)
    assert rows[0]["vehicle_id"] == vehicle_with_price
    assert rows[0]["is_money_pit"] is True

    pits = profitability.fleet_profitability(only_money_pits=True, conn=conn)
    assert [row["vehicle_id"] for row in pits] == [vehicle_with_price]


def test_fleet_summary_matches_the_rows_beneath_it(
    admin, conn, sample_customer, sample_vehicle, vehicle_with_price
):
    """الملخّص يساوي مجموع الجدول: رقمان متناقضان على شاشة واحدة عطب."""
    _rent(sample_customer, sample_vehicle, 50, 10, conn)
    expenses_repo.add_expense(vehicle_with_price, "tyres", 90000, conn=conn)

    rows = profitability.fleet_profitability(conn=conn)
    summary = profitability.fleet_summary(conn=conn)

    assert summary["vehicles_count"] == len(rows)
    assert summary["total_revenue"] == sum(row["total_revenue"] for row in rows)
    assert summary["total_expenses"] == sum(row["total_expenses"] for row in rows)
    assert summary["net_profit"] == summary["total_revenue"] - summary["total_expenses"]
    assert summary["invested"] == 2_000_000          # السيارة الأخرى بلا ثمن مسجَّل


def test_breakdown_answers_where_the_money_went(admin, conn, vehicle_with_price):
    expenses_repo.add_expense(vehicle_with_price, "tyres", 90000, conn=conn)
    expenses_repo.add_expense(vehicle_with_price, "tyres", 30000, conn=conn)
    expenses_repo.add_expense(vehicle_with_price, "oil", 12000, conn=conn)

    breakdown = {row["expense_type"]: row for row in
                 profitability.expense_breakdown(vehicle_with_price, conn=conn)}
    assert breakdown["tyres"]["total"] == 120000
    assert breakdown["tyres"]["entries"] == 2
    assert breakdown["oil"]["total"] == 12000


def test_exchange_rate_changes_do_not_rewrite_past_expenses(admin, conn,
                                                            vehicle_with_price):
    """المصروف يحفظ لقطة سعر صرفه، فلا تتبدّل أرقام الماضي بتعديل سعر اليوم."""
    from app.repositories import settings_repo

    settings_repo.set_exchange_rate("USD", "5", conn=conn)
    expenses_repo.add_expense(vehicle_with_price, "tyres", 10000,
                              currency_code="USD", conn=conn)

    before = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert before["total_expenses"] == 50000          # 100.00 دولاراً × 5

    settings_repo.set_exchange_rate("USD", "9", conn=conn)

    after = profitability.vehicle_profitability(vehicle_with_price, conn=conn)
    assert after["total_expenses"] == before["total_expenses"]


# ---------------------------------------------------------------------------
# مستودع المصروفات
# ---------------------------------------------------------------------------
def test_expense_requires_a_positive_amount(admin, conn, vehicle_with_price):
    with pytest.raises(ValueError):
        expenses_repo.add_expense(vehicle_with_price, "oil", 0, conn=conn)


def test_expense_rejects_an_unknown_type(admin, conn, vehicle_with_price):
    with pytest.raises(ValueError):
        expenses_repo.add_expense(vehicle_with_price, "fuel", 5000, conn=conn)


def test_expense_rejects_a_future_date(admin, conn, vehicle_with_price):
    """تكلفةٌ لم تُصرف بعد تُفسد حساب ربح اليوم."""
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        expenses_repo.add_expense(vehicle_with_price, "oil", 5000,
                                  date=tomorrow, conn=conn)


def test_expense_rejects_an_unknown_vehicle(admin, conn):
    with pytest.raises(ValueError):
        expenses_repo.add_expense(99999, "oil", 5000, conn=conn)


def test_expense_defaults_to_the_vehicle_currency(admin, conn, vehicle_with_price):
    expense_id = expenses_repo.add_expense(vehicle_with_price, "oil", 5000, conn=conn)
    row = expenses_repo.get(expense_id, conn=conn)
    assert row["currency_code"] == "LYD"
    assert row["rate_to_base"] == money.RATE_SCALE
    assert row["date"] == TODAY.isoformat()


def test_expense_can_be_edited(admin, conn, vehicle_with_price):
    expense_id = expenses_repo.add_expense(vehicle_with_price, "oil", 5000, conn=conn)
    expenses_repo.update_expense(expense_id, "tyres", 90000, _days_ago(3),
                                 notes="أربعة إطارات", conn=conn)

    row = expenses_repo.get(expense_id, conn=conn)
    assert row["expense_type"] == "tyres"
    assert row["amount"] == 90000
    assert row["notes"] == "أربعة إطارات"
    assert expenses_repo.total_for_vehicle(vehicle_with_price, conn=conn) == 90000


def test_only_an_admin_deletes_an_expense(admin, conn, vehicle_with_price):
    """الحذف للمدير وحده: رقمٌ يُمحى يجعل سيارة خاسرة تبدو رابحة."""
    from app.repositories import users_repo

    expense_id = expenses_repo.add_expense(vehicle_with_price, "oil", 5000, conn=conn)

    staff = users_repo.create("kateb", "كاتب", "Staff#12345", "staff", conn=conn)
    session.login(session.CurrentUser(staff, "kateb", "كاتب", "staff"))
    with pytest.raises(session.PermissionDenied):
        expenses_repo.delete_expense(expense_id, conn=conn)

    session.login(admin)
    expenses_repo.delete_expense(expense_id, conn=conn)
    assert expenses_repo.get(expense_id, conn=conn) is None


def test_deleting_a_vehicle_takes_its_expenses_with_it(admin, conn):
    """``ON DELETE CASCADE``: لا مصروف معلّق بلا سيارة."""
    vehicle_id = vehicles_repo.create(
        {"brand": "كيا", "model": "ريو", "year": 2020, "plate_number": "8-80000",
         "color": "رمادي", "daily_rate": 9000, "currency_code": "LYD"},
        conn=conn,
    )
    expenses_repo.add_expense(vehicle_id, "oil", 5000, conn=conn)
    vehicles_repo.delete(vehicle_id, conn=conn)

    assert db.scalar(
        "SELECT COUNT(*) FROM vehicle_expenses WHERE vehicle_id = ?",
        (vehicle_id,), conn=conn, default=0,
    ) == 0


def test_the_database_itself_refuses_an_unknown_expense_type(conn, sample_vehicle):
    """الضمانة في المحرّك لا في طبقة الخدمة وحدها."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO vehicle_expenses (vehicle_id, expense_type, amount,
                                             currency_code, date)
               VALUES (?, 'petrol', 1000, 'LYD', ?)""",
            (sample_vehicle, TODAY.isoformat()),
        )


def test_the_module_is_a_pro_feature(admin, conn, vehicle_with_price):
    """وحدة الربحية خارج النسخة الأساسية — يُمنع العمل لا يُخفى الزرّ فقط."""
    features.set_tier(features.TIER_BASIC)
    try:
        with pytest.raises(features.FeatureLocked):
            expenses_repo.add_expense(vehicle_with_price, "oil", 5000, conn=conn)
        with pytest.raises(features.FeatureLocked):
            profitability.fleet_profitability(conn=conn)
    finally:
        features.set_tier(features.TIER_PRO)


def test_period_report_counts_the_whole_cost_ledger(admin, conn, vehicle_with_price):
    """تقرير الفترة يقرأ الدفتر الموحّد، فلا تُعطي شاشتان رقمين مختلفين.

    قبل وحدة الربحية كان «مصاريف الصيانة» في تقرير الفترة يجمع سجلّ الورشة
    وحده. ولو بقي كذلك بعدها لظهر ثمن الإطارات في شاشة الربحية وغاب عن تقرير
    الشهر — ولا يملك صاحب المكتب ما يرجّح بين الرقمين.
    """
    from app.services import reporting

    maintenance_repo.open_maintenance(vehicle_with_price, "إصلاح", cost=250000, conn=conn)
    expenses_repo.add_expense(vehicle_with_price, "tyres", 90000, conn=conn)

    start = (TODAY - datetime.timedelta(days=1)).isoformat()
    end = (TODAY + datetime.timedelta(days=1)).isoformat()
    report = reporting.revenue_report(start, end, conn=conn)

    assert report["maintenance_cost"] == 250000       # الورشة وحدها
    assert report["expenses_cost"] == 340000          # الورشة + الإطارات
    assert report["net"] == report["collected"] - report["expenses_cost"]

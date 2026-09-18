# -*- coding: utf-8 -*-
"""تلوين صفوف الجداول: ما يُعرف بلمحة قبل فتح أي ملفّ.

الموظّف أمام زبون واقف لا يفتح ملفّ كل اسم ليعرف أمحظورٌ هو أم بيده سيارة.
فالجدول نفسه يقول ذلك — والاختبار هنا **يقرأ لون الخليّة فعلاً** لا يفحص أن
دالّةً اسمها ``_row_color`` موجودة.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.repositories import customers_repo  # noqa: E402
from app.services import rental_service  # noqa: E402
from app.ui.widgets.common import ROW_ACTIVE, ROW_DANGER, DataTable  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _row_background(table, row):
    return table.model_.item(row, 0).background().color()


# ---------------------------------------------------------------------------
# آلة التلوين نفسها
# ---------------------------------------------------------------------------
def test_the_table_paints_the_whole_row(qt_app):
    """اللون يعمّ خلايا الصفّ كلّها لا خليّةً واحدة."""
    table = DataTable([("name", "الاسم"), ("note", "ملاحظة")])
    rows = [{"name": "أحمد", "note": "ـ"}, {"name": "سالم", "note": "ـ"}]

    table.fill(rows, lambda row, key: row[key],
               lambda row: ROW_DANGER if row["name"] == "أحمد" else None)

    for column in range(2):
        assert table.model_.item(0, column).background().color() == ROW_DANGER
    assert table.model_.item(1, 0).background().color() != ROW_DANGER


def test_alternating_colors_step_aside_for_status_colors(qt_app):
    """التلوين المتناوب يُطفأ حين يكون للجدول ألوان حالة.

    وإلّا خرج صفٌّ أحمر في موضع زوجي بلون بين الأحمر والرمادي لا يُميَّز.
    """
    table = DataTable([("name", "الاسم")])

    table.fill([{"name": "أحمد"}], lambda row, key: row[key],
               lambda row: ROW_DANGER)
    assert not table.alternatingRowColors()

    table.fill([{"name": "أحمد"}], lambda row, key: row[key])
    assert table.alternatingRowColors()


# ---------------------------------------------------------------------------
# قاعدة التلوين في شاشة العملاء
# ---------------------------------------------------------------------------
def _blacklist(customer_id, conn):
    """يُدرج عميلاً في القائمة السوداء. ``update`` تحديث كامل لا جزئي، فيُعاد
    إرسال الاسم معه وإلّا رُفض التحديث لغياب حقل إلزامي."""
    current = customers_repo.get(customer_id, conn=conn)
    customers_repo.update(
        customer_id,
        {"full_name": current["full_name"], "is_blacklisted": 1,
         "blacklist_reason": "شيك بلا رصيد"},
        conn=conn,
    )


def _color_of(row):
    from app.ui.pages.customers_page import CustomersPage

    return CustomersPage._row_color(row)


def test_a_blacklisted_customer_is_red(conn, admin, sample_customer):
    _blacklist(sample_customer, conn)
    row = customers_repo.search(conn=conn)[0]
    assert _color_of(row) == ROW_DANGER


def test_a_customer_holding_a_car_is_green(conn, admin, sample_contract):
    row = customers_repo.search(conn=conn)[0]
    assert row["open_contracts"] == 1
    assert _color_of(row) == ROW_ACTIVE


def test_an_ordinary_customer_has_no_color(conn, admin, sample_customer):
    row = customers_repo.search(conn=conn)[0]
    assert _color_of(row) is None


def test_red_wins_over_green(conn, admin, sample_customer, sample_contract):
    """محظورٌ بيده سيارة الآن يخرج **أحمر** لا أخضر.

    هي الحالة التي يُراد التنبّه لها فعلاً، ولا يجوز أن يُخفيها الأخضر لأن
    للعميل عقداً مفتوحاً.
    """
    _blacklist(sample_customer, conn)

    row = customers_repo.search(conn=conn)[0]
    assert row["open_contracts"] == 1, "لم يعد العقد مفتوحاً فلا يختبر شيئاً"
    assert row["is_blacklisted"] == 1
    assert _color_of(row) == ROW_DANGER


def test_a_closed_contract_no_longer_greens_the_customer(
        conn, admin, sample_contract):
    """اللون الأخضر يقول «بيده سيارة الآن» — فيزول بعودتها."""
    assert _color_of(customers_repo.search(conn=conn)[0]) == ROW_ACTIVE

    rental_service.close_contract(sample_contract, conn=conn)
    assert _color_of(customers_repo.search(conn=conn)[0]) is None


def test_a_cancelled_contract_row_is_red(conn, admin, sample_contract):
    from app.repositories import contracts_repo
    from app.ui.pages.contracts_page import ContractsPage

    rental_service.cancel_contract(sample_contract, conn=conn)
    row = contracts_repo.get(sample_contract, conn=conn)
    assert ContractsPage._row_color(row) == ROW_DANGER

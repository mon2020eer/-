# -*- coding: utf-8 -*-
"""كشف حساب المبيعات: الجرد الكامل.

التجهيزة هنا هي **أمثلة صاحب المكتب الأربعة حرفياً**، لأنها ليست حالات
مُختلَقة بل ما يقع في يوم عمل:

    ١) عقد ٩٠٠ استُلمت قيمته كاملة
    ٢) عقد ٦٠٠ أُلغي بعد قبض عربون ١٠٠
    ٣) عقد ٨٠٠ دُفع نصفه
    ٤) عقد ١٬٠٠٠ بخصم ٢٠٠

والحارس الأهمّ فيها هو **مطابقة الأرقام**: كشفٌ أرقامه لا يفسّر بعضها بعضاً
يُفقد الثقة بكل رقم آخر في المنظومة، وهو أسوأ من لا كشف.
"""

import datetime

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtPdf import QPdfDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.core import features, money  # noqa: E402
from app.repositories import customers_repo, payments_repo, settings_repo, vehicles_repo  # noqa: E402
from app.services import rental_service, statement  # noqa: E402

# الفترة التي تقع فيها كل عقود التجهيزة
PERIOD = ("2026-03-01", "2026-03-31")
_BASE = datetime.date(2026, 3, 2)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _vehicle(conn, plate, daily_rate, currency="LYD"):
    return vehicles_repo.create({
        "brand": "تويوتا", "model": "كورولا", "year": 2022,
        "plate_number": plate, "color": "أبيض",
        "daily_rate": daily_rate, "currency_code": currency,
    }, conn=conn)


@pytest.fixture()
def four_cases(conn, admin, sample_customer):
    """أمثلة المالك الأربعة، ويُرجع أرقام عقودها بالترتيب."""
    numbers = {}

    def open_on(offset, vehicle, days, discount=0):
        start = _BASE + datetime.timedelta(days=offset)
        return rental_service.open_contract(
            sample_customer, vehicle, start.isoformat(),
            (start + datetime.timedelta(days=days)).isoformat(),
            discount=discount, conn=conn,
        )

    # ١) ٩٠٠ مدفوعة كاملةً — ٣٠٠ × ٣ أيام
    paid_id, numbers["paid"] = open_on(0, _vehicle(conn, "1-1", 30000), 3)
    payments_repo.add(paid_id, 90000, conn=conn)

    # ٢) ٦٠٠ أُلغي بعد عربون ١٠٠
    cancelled_id, numbers["cancelled"] = open_on(1, _vehicle(conn, "2-2", 30000), 2)
    payments_repo.add(cancelled_id, 10000, conn=conn)
    rental_service.cancel_contract(cancelled_id, reason="طلب العميل", conn=conn)

    # ٣) ٨٠٠ دُفع نصفها
    half_id, numbers["half"] = open_on(2, _vehicle(conn, "3-3", 40000), 2)
    payments_repo.add(half_id, 40000, conn=conn)

    # ٤) ١٬٠٠٠ بخصم ٢٠٠
    _, numbers["discounted"] = open_on(3, _vehicle(conn, "4-4", 50000), 2,
                                       discount=20000)

    return numbers


# ---------------------------------------------------------------------------
# الحساب
# ---------------------------------------------------------------------------
def test_the_four_cases_add_up_exactly(conn, admin, four_cases):
    """كل رقم في الملخّص، محسوباً باليد ومقارَناً."""
    summary = statement.reconciliation(*PERIOD, conn=conn)

    assert summary["contracts"] == 4
    assert summary["active_count"] == 3
    assert summary["cancelled_count"] == 1

    # ٩٠٠ + ٨٠٠ + ١٬٠٠٠ = ٢٬٧٠٠ (الملغى خارجها)
    assert money.to_major(summary["gross"]) == 2700
    assert money.to_major(summary["discount"]) == 200
    assert money.to_major(summary["revenue"]) == 2500        # ٢٬٧٠٠ − ٢٠٠
    assert money.to_major(summary["collected"]) == 1300      # ٩٠٠ + ٤٠٠
    assert money.to_major(summary["outstanding"]) == 1200    # ٤٠٠ + ٨٠٠

    # الملغى: قيمته خارج الإيراد، وعربونه نقدٌ في الصندوق
    assert money.to_major(summary["cancelled_value"]) == 600
    assert money.to_major(summary["cancelled_kept"]) == 100


def test_the_numbers_explain_each_other(conn, admin, four_cases):
    """العلاقات محفوظة، لا أرقام مستقلّة يصادف أنها صحيحة.

    كشفٌ لا تفسّر أرقامه بعضها يجعل صاحب المكتب يظنّ أن البرنامج يكذب، فيفقد
    الثقة بكل رقم آخر فيه.
    """
    summary = statement.reconciliation(*PERIOD, conn=conn)

    assert summary["revenue"] == summary["gross"] - summary["discount"]
    assert summary["outstanding"] == summary["revenue"] - summary["collected"]
    assert summary["active_count"] == (summary["contracts"]
                                       - summary["cancelled_count"])


def test_the_cancelled_contract_is_shown_but_not_counted(conn, admin, four_cases):
    """يظهر في الورقة ويُستثنى من الإيراد — ولا يُحذف.

    كشفٌ يُسقط عقداً بصمت يجعل صاحب المكتب يظنّ أن المنظومة فقدته.
    """
    lines = statement.sales_lines(*PERIOD, conn=conn)
    numbers = [row["contract_number"] for row in lines]
    assert four_cases["cancelled"] in numbers, "العقد الملغى غائب عن الكشف"

    cancelled = next(row for row in lines
                     if row["contract_number"] == four_cases["cancelled"])
    assert cancelled["status"] == "cancelled"

    summary = statement.reconciliation(*PERIOD, conn=conn)
    assert money.to_major(summary["revenue"]) == 2500, "قيمة الملغى دخلت الإيراد"


def test_cash_follows_the_payment_date_not_the_contract_date(conn, admin, four_cases):
    """النقد أساسه تاريخ الدفعة.

    دفعاتُ التجهيزة سُجّلت اليوم على عقود مارس، فنقدُ مارس صفر ونقدُ اليوم
    ١٬٤٠٠ — وهذا **هو الصواب**: صندوق المكتب امتلأ يوم القبض لا يوم العقد.
    """
    march = statement.reconciliation(*PERIOD, conn=conn)
    assert march["cash_in"] == 0, "نقدٌ نُسب إلى شهر لم يُقبض فيه"

    today = datetime.date.today().isoformat()
    now = statement.reconciliation(today, today, conn=conn)
    # ٩٠٠ + ١٠٠ + ٤٠٠ — ومنها عربون عقد ملغى، فهو نقدٌ بلا إيراد
    assert money.to_major(now["cash_in"]) == 1400


# ---------------------------------------------------------------------------
# التقسيم الزمني
# ---------------------------------------------------------------------------
def test_granularity_changes_how_many_groups_come_back(conn, admin, four_cases):
    """العقود الأربعة في أربعة أيام من شهر واحد من سنة واحدة."""
    year = ("2026-01-01", "2026-12-31")

    assert len(statement.period_totals(*year, "daily", conn=conn)) == 4
    assert len(statement.period_totals(*year, "monthly", conn=conn)) == 1
    assert len(statement.period_totals(*year, "yearly", conn=conn)) == 1

    weekly = statement.period_totals(*year, "weekly", conn=conn)
    assert 1 <= len(weekly) <= 2, "أربعة أيام متتالية لا تقع في أكثر من أسبوعين"


def test_period_rows_carry_the_same_totals_as_the_summary(conn, admin, four_cases):
    """مجموع الفترات الفرعية = الملخّص. جدولان يختلفان يُبطلان الورقة."""
    rows = statement.period_totals(*PERIOD, "daily", conn=conn)
    summary = statement.reconciliation(*PERIOD, conn=conn)

    assert sum(row["revenue"] for row in rows) == summary["revenue"]
    assert sum(row["discount"] for row in rows) == summary["discount"]
    assert sum(row["collected"] for row in rows) == summary["collected"]
    assert sum(row["contracts"] for row in rows) == summary["contracts"]


def test_an_unknown_granularity_is_refused(conn, admin):
    with pytest.raises(statement.StatementError):
        statement.period_totals(*PERIOD, "hourly", conn=conn)


def test_weekly_labels_are_readable_arabic(conn, admin):
    assert statement.period_label("weekly", "2026-09") == "الأسبوع 9 من 2026"
    assert statement.period_label("monthly", "2026-09") == "2026-09"


# ---------------------------------------------------------------------------
# العملات
# ---------------------------------------------------------------------------
def test_totals_use_the_rate_stored_in_each_contract(conn, admin, sample_customer):
    """كشف الشهر الماضي لا يتغيّر حين يُعدَّل سعر الصرف اليوم.

    كل عقد يحمل سعر صرفه وقت إنشائه. ولو جُمعت المبالغ بسعر اليوم لتغيّرت
    أرقام كشفٍ طُبع ووُقّع — وهي حجّة عند الخلاف.
    """
    settings_repo.set_exchange_rate("USD", 5, conn=conn)

    start = _BASE.isoformat()
    end = (_BASE + datetime.timedelta(days=2)).isoformat()
    rental_service.open_contract(
        sample_customer, _vehicle(conn, "9-9", 10000, currency="USD"),
        start, end, conn=conn,
    )

    before = statement.reconciliation(*PERIOD, conn=conn)["revenue"]

    settings_repo.set_exchange_rate("USD", 9, conn=conn)
    after = statement.reconciliation(*PERIOD, conn=conn)["revenue"]

    assert after == before, "تغيّر سعر الصرف اليوم فغيّر كشف فترة ماضية"


# ---------------------------------------------------------------------------
# الحدود
# ---------------------------------------------------------------------------
def test_a_backwards_period_is_refused_not_silently_empty(conn, admin):
    """فترة مقلوبة ترفع خطأً ولا تُخرج ورقة تقول «لا مبيعات».

    استعلامٌ بفترة مقلوبة يُرجع صفر صفوف بلا خطأ، فتخرج ورقة رسمية كاذبة —
    وهي أسوأ من رسالة خطأ لأنها تُصدَّق.
    """
    for call in (statement.sales_lines, statement.reconciliation):
        with pytest.raises(statement.StatementError):
            call("2026-12-31", "2026-01-01", conn=conn)


def test_an_empty_period_is_a_valid_but_honest_statement(conn, admin):
    """فترة بلا عقود تُخرج كشفاً صحيحاً أصفاره حقيقية."""
    summary = statement.reconciliation("2020-01-01", "2020-01-31", conn=conn)
    assert summary["contracts"] == 0
    assert summary["revenue"] == 0
    assert statement.sales_lines("2020-01-01", "2020-01-31", conn=conn) == []


def test_the_statement_is_pro_only(conn, admin, four_cases):
    """قرار المالك: الكشف في النسخة المتقدّمة وحدها.

    والمنع في **طبقة الخدمة** لا بإخفاء الزرّ: نسخةٌ أساسية تصل الدالّة
    بطريقة أخرى يجب أن تُردّ.
    """
    features.set_tier(features.TIER_BASIC)
    try:
        for call in (statement.sales_lines, statement.reconciliation,
                     statement.build_html, statement.export_pdf):
            with pytest.raises(Exception) as error:
                call(*PERIOD, conn=conn)
            assert "StatementError" not in type(error.value).__name__
    finally:
        features.set_tier(features.TIER_PRO)


# ---------------------------------------------------------------------------
# الورقة
# ---------------------------------------------------------------------------
def _pdf_pages(path):
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    return [document.getAllText(page).text()
            for page in range(document.pageCount())]


def test_every_contract_reaches_the_paper(qt_app, conn, admin, four_cases, tmp_path):
    """كل عقد من الأربعة في الورقة بقيمته.

    يُبحث عن **جزء الرقم** لا الرقم كاملاً: استخراج النصّ من PDF يعيد ترتيب
    المقاطع اللاتينية داخل سطر عربي («CR-2026-0001» ← «-2026-0001CR») وهو
    أثر الاستخراج لا أثر الطباعة.
    """
    output = tmp_path / "كشف.pdf"
    statement.export_pdf(*PERIOD, "daily", output_path=output, conn=conn)

    text = "\n".join(_pdf_pages(output))
    for number in four_cases.values():
        assert number.split("-", 1)[1] in text, number

    for value in ("900.00", "600.00", "800.00", "1,000.00", "200.00"):
        assert value in text, value


def test_a_cancelled_line_shows_no_phantom_debt(qt_app, conn, admin, four_cases,
                                                tmp_path):
    """العقد الملغى لا دَين عليه، فعمود «المتبقّي» فيه شرطة لا رقم.

    عرضُ رصيده رقماً يجعل المكتب يطالب عميلاً بمال عن عقد أُلغي، ويجعل مجموع
    العمود يخالف سطر الملخّص الذي يستثنيه.
    """
    html = statement.build_html(*PERIOD, "daily", conn=conn)

    cancelled_row = [line for line in html.split("<tr")
                     if 'class="cancelled"' in line]
    assert cancelled_row, "لا صفّ مميَّز للعقد الملغى"
    assert "—" in cancelled_row[0], "الملغى يعرض متبقّياً وهمياً"


def test_long_statements_are_numbered_on_every_page(qt_app, conn, admin,
                                                    sample_customer, tmp_path):
    """كشفٌ يتجاوز صفحة يحمل «صفحة س من ص» على كل ورقة.

    ورقة حساب بلا ترقيم تُفقد صفحةٌ منها بلا أن يُلاحظ أحد — ولا شيء في
    الأرقام يكشف النقص.
    """
    for index in range(40):
        start = _BASE + datetime.timedelta(days=index % 20)
        rental_service.open_contract(
            sample_customer, _vehicle(conn, "L-%d" % index, 10000),
            start.isoformat(),
            (start + datetime.timedelta(days=1)).isoformat(),
            conn=conn,
        )

    output = tmp_path / "طويل.pdf"
    statement.export_pdf(*PERIOD, "daily", output_path=output, conn=conn)

    pages = _pdf_pages(output)
    assert len(pages) >= 2, "لم يتجاوز الكشف صفحةً واحدة فلا يختبر شيئاً"
    for index, text in enumerate(pages):
        assert "صفحة" in text, "الصفحة %d بلا ترقيم" % (index + 1)


def test_the_statement_lands_in_the_archive_by_default(qt_app, conn, admin,
                                                       four_cases, tmp_path):
    """بلا مسار صريح يُحفظ في مجلد الأرشيف، في مجلد «كشوفات» فرعي."""
    from app.services import printing

    chosen = tmp_path / "أرشيف"
    printing.set_archive_root(chosen, conn=conn)

    path = statement.export_pdf(*PERIOD, "monthly", conn=conn)

    assert str(chosen) in str(path)
    assert statement.ARCHIVE_SUBFOLDER in str(path)
    assert "2026" in str(path), "لم يُصنَّف بسنة بداية الفترة"


def test_printing_without_a_printer_still_keeps_the_file(qt_app, conn, admin,
                                                        four_cases):
    """غياب الطابعة ليس خطأً: الكشف محفوظ، ويُطبع من مكانه."""
    import pathlib

    from app.services import printing

    if printing.default_printer_name() is not None:
        pytest.skip("هذا الجهاز فيه طابعة، والحارس موضوعه غيابها")

    path, printer = statement.print_statement(*PERIOD, "monthly", conn=conn)
    assert printer is None
    assert pathlib.Path(path).is_file()

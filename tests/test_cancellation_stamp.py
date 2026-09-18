# -*- coding: utf-8 -*-
"""ختم الإلغاء: على الشاشة وعلى الورقة.

عقدٌ مُلغى تبقى نسخته المطبوعة في يد الزبون، وقد تجاور ورقةً سارية في ملفّ
واحد. فما يميّزهما يجب أن يكون **على الورقة نفسها** لا في شاشة المكتب وحدها،
وعلى **كل صفحة** منها: صفحة الشروط إن فُصلت عن الأولى بدت عقداً قائماً.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QMarginsF, QSize  # noqa: E402
from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument  # noqa: E402
from PyQt6.QtPdf import QPdfDocument  # noqa: E402
from PyQt6.QtPrintSupport import QPrinter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.repositories import contracts_repo  # noqa: E402
from app.services import contract_pdf, rental_service  # noqa: E402

STAMP_START = "تم إلغاء العقد"


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _pages_text(path):
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    return [document.getAllText(page).text()
            for page in range(document.pageCount())]


def _red_ink_ratio(path, page):
    """نسبة البكسلات المائلة إلى الحمرة في صفحة مُصيَّرة.

    **لماذا قياس الحبر لا قراءة النصّ؟** لأن الختم مرسوم مائلاً بـ ``QPainter``،
    واستخراج النصّ من PDF يفكّ الحروف المُدارة إلى رموز متناثرة («ع لا ء غا لإم
    ت») فلا تُجمع كلمةً — قيس هذا فعلاً على ناتج مولَّد. أمّا الحبر الأحمر على
    ورقة سوداء وبيضاء فدليلٌ لا يلتبس.
    """
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    image = document.render(page, QSize(420, 594))

    reddish = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.red() > color.green() + 15 and color.red() > color.blue() + 15:
                reddish += 1
    return reddish / float(image.width() * image.height())


# ---------------------------------------------------------------------------
# ما يُحفظ
# ---------------------------------------------------------------------------
def test_cancelling_records_the_date_and_the_user(conn, admin, sample_contract):
    rental_service.cancel_contract(sample_contract, reason="تجربة", conn=conn)

    contract = contracts_repo.get(sample_contract, conn=conn)
    assert contract["status"] == "cancelled"
    assert contract["cancelled_at"], "لم يُحفظ تاريخ الإلغاء"
    assert contract["cancelled_by_name"] == admin.full_name


def test_the_user_name_is_copied_not_referenced(conn, admin, sample_contract):
    """الاسم يُنسخ نصّاً لا يُشار إليه بمعرّف.

    المستخدم قد يُحذف أو يتغيّر اسمه بعد سنة، والورقة المطبوعة لا تُعاد
    كتابتها — فمرجعٌ رقمي كان سيجعل ختمها يشير إلى لا أحد.
    """
    rental_service.cancel_contract(sample_contract, conn=conn)

    stored = conn.execute(
        "SELECT cancelled_by_name FROM contracts WHERE id = ?", (sample_contract,)
    ).fetchone()[0]
    assert stored == admin.full_name
    assert not str(stored).isdigit()


# ---------------------------------------------------------------------------
# صياغة الختم
# ---------------------------------------------------------------------------
def test_an_open_contract_has_no_stamp(conn, admin, sample_contract):
    contract = contracts_repo.get(sample_contract, conn=conn)
    assert contract_pdf.cancellation_stamp(contract) is None


def test_the_stamp_names_the_date_and_the_user(conn, admin, sample_contract):
    rental_service.cancel_contract(sample_contract, conn=conn)
    contract = contracts_repo.get(sample_contract, conn=conn)

    stamp = contract_pdf.cancellation_stamp(contract)
    assert stamp.startswith(STAMP_START)
    assert "بتاريخ" in stamp
    assert "بواسطة المستخدم %s" % admin.full_name in stamp


def test_a_contract_cancelled_before_the_upgrade_still_gets_a_stamp(
        conn, admin, sample_contract):
    """عقدٌ أُلغي بالنسخة السابقة لا تاريخ إلغاء فيه — والحالة هي الحقيقة.

    لا يجوز أن يخرج بلا ختم لأن عموداً لم يكن موجوداً يوم أُلغي.
    """
    rental_service.cancel_contract(sample_contract, conn=conn)
    conn.execute(
        "UPDATE contracts SET cancelled_at = NULL, cancelled_by_name = NULL"
        " WHERE id = ?", (sample_contract,)
    )
    conn.commit()

    stamp = contract_pdf.cancellation_stamp(contracts_repo.get(sample_contract, conn=conn))
    assert stamp is not None and stamp.startswith(STAMP_START)


# ---------------------------------------------------------------------------
# على الورقة
# ---------------------------------------------------------------------------
def test_the_printed_contract_states_the_cancellation_in_words(
        qt_app, conn, admin, sample_contract, tmp_path):
    """الشريط الأفقي أعلى الورقة: نصٌّ يُقرأ ويُصوَّر ويُرسَل.

    الختم المائل يُرى ولا يُستخرج نصّاً، فلا يكفي وحده: من يفتح الملف على
    حاسوبه ويبحث عن كلمة «مُلغى» يجب أن يجدها.
    """
    rental_service.cancel_contract(sample_contract, conn=conn)

    output = tmp_path / "ملغى.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    assert STAMP_START in _pages_text(output)[0]


def test_the_stamp_is_inked_on_every_page(
        qt_app, conn, admin, sample_contract, tmp_path):
    rental_service.cancel_contract(sample_contract, conn=conn)

    output = tmp_path / "ملغى.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    document = QPdfDocument(None)
    assert document.load(str(output)) == QPdfDocument.Error.None_

    for page in range(document.pageCount()):
        assert _red_ink_ratio(output, page) > 0.001, \
            "الصفحة %d بلا ختم مرئي" % (page + 1)


def test_a_live_contract_is_printed_without_a_stamp(
        qt_app, conn, admin, sample_contract, tmp_path):
    """الحارس المقابل: عقدٌ سارٍ لا يُختم — وإلّا صار الختم بلا معنى."""
    output = tmp_path / "سارٍ.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    assert STAMP_START not in _pages_text(output)[0]
    assert _red_ink_ratio(output, 0) < 0.001, "ورقة عقد سارٍ عليها حبر أحمر"


def test_every_page_is_printed_once_and_only_once(qt_app, tmp_path):
    """الطباعة اليدوية صفحةً صفحة لا تُكرّر المستند على كل صفحة.

    هذا عطب الطريقة المستعملة إن أُهمل القصّ والإزاحة: يخرج المستند كاملاً
    فوق كل ورقة، فتتشابه الصفحات ولا يُقرأ منها شيء. ويُكشف بمستند طويل
    عمداً: علامةٌ في أوّله وأخرى في آخره يجب أن تفترقا صفحةً عن صفحة.
    """
    document = QTextDocument()
    document.setHtml(
        '<html dir="rtl"><body><p>البداية_الفريدة</p>'
        + ("<p>سطر حشو لإطالة المستند حتى يتجاوز صفحةً واحدة.</p>" * 120)
        + "<p>النهاية_الفريدة</p></body></html>"
    )

    output = tmp_path / "طويل.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(output))
    printer.setPageLayout(QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(14, 14, 14, 14),
        QPageLayout.Unit.Millimeter,
    ))

    contract_pdf._print_with_watermark(document, printer, STAMP_START)

    pages = _pages_text(output)
    assert len(pages) >= 2, "لم يتجاوز المستند صفحةً واحدة فلا يختبر شيئاً"

    assert "البداية_الفريدة" in pages[0]
    assert "البداية_الفريدة" not in pages[-1], "المستند كلّه يُطبع على كل صفحة"
    assert "النهاية_الفريدة" in pages[-1]
    assert "النهاية_الفريدة" not in pages[0]

    # والختم على كل صفحة من هذا المستند المتعدّد الصفحات
    for page in range(len(pages)):
        assert _red_ink_ratio(output, page) > 0.001, \
            "الصفحة %d بلا ختم" % (page + 1)

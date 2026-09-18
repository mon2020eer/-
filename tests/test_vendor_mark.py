# -*- coding: utf-8 -*-
"""هوية المزوّد: داخل البرنامج لا على الورق، ولا يُزيلها المكتب.

المسألة التي تحرسها هذه الاختبارات **خلطٌ وقع فعلاً**: اسم المزوّد
(«شركة المسار المتحد») وُضع افتراضاً في خانة اسم المكتب، فصار يُطبع في ترويسة
عقود العميل. والصواب هويّتان منفصلتان:

    • **هوية المكتب** — يضبطها المكتب، وتُطبع في ترويسة عقوده وتقاريره.
    • **هوية المزوّد** — ثابتة في الشيفرة، تظهر داخل البرنامج، ولا تدخل ورقةً.

وكلا الاتجاهين محروس هنا: أن اسم المزوّد **موجود في الواجهة**، وأنه
**غائب عن كل ما يُطبع**.

⚠ وحدّ هذه الحماية مذكور صراحةً: هي تمنع الإزالة **من داخل البرنامج** — لا
  إعداد ولا شاشة ولا ملف نصّي يحذف الاسم. ومن يملك الشيفرة المصدرية يغيّر أي
  سطر فيها، والمانع الحقيقي للاستعمال غير المرخَّص هو نظام المفاتيح الموقَّعة.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtPdf import QPdfDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from app import config  # noqa: E402
from app.repositories import settings_repo  # noqa: E402
from app.services import contract_pdf, reporting  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _labels(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def _pdf_text(path):
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    return "\n".join(document.getAllText(page).text()
                     for page in range(document.pageCount()))


# ---------------------------------------------------------------------------
# الهويّتان منفصلتان
# ---------------------------------------------------------------------------
def test_the_vendor_name_is_not_the_default_office_name(conn, admin):
    """الحارس الذي يمنع تكرار الخلط.

    كان اسم المزوّد مزروعاً في ``office_name``، فخرج عقدُ العميل الأول يحمل
    اسم من باعه البرنامج بدل اسم مكتبه.
    """
    assert config.DEFAULT_SETTINGS["office_name"] != config.VENDOR_NAME
    assert settings_repo.get("office_name", conn=conn) != config.VENDOR_NAME


def test_the_vendor_name_is_not_a_setting_at_all(conn, admin):
    """ليس صفّاً في قاعدة البيانات، فلا شيء يُعدَّل ولا شيء يُحذف."""
    stored = settings_repo.all_settings(conn=conn)
    assert config.VENDOR_NAME not in stored.values()
    for key in stored:
        assert "vendor" not in key.lower()


def test_no_settings_key_can_blank_the_vendor_name(conn, admin):
    """محاولةُ إخفائه بإعداد مُختلَق لا تغيّر شيئاً.

    الاسم ثابتٌ في الشيفرة، فكتابة أي مفتاح في ``app_settings`` — حتى بالاسم
    نفسه — لا تمسّه.
    """
    for key in ("vendor_name", "VENDOR_NAME", "developer", "powered_by"):
        settings_repo.set_value(key, "", conn=conn)

    assert config.VENDOR_NAME == "شركة المسار المتحد"


# ---------------------------------------------------------------------------
# حاضرٌ في البرنامج
# ---------------------------------------------------------------------------
def test_the_login_screen_shows_the_vendor(qt_app, conn, admin):
    from app.ui.login_window import LoginWindow

    window = LoginWindow()
    try:
        assert any(config.VENDOR_NAME in text for text in _labels(window)), \
            "اسم المزوّد غائب عن شاشة الدخول"
    finally:
        window.deleteLater()


def test_the_sidebar_shows_the_vendor_on_every_screen(qt_app, conn, admin):
    """الشريط الجانبي ظاهرٌ مع كل صفحة، فالاسم حاضر في كل لقطة شاشة."""
    from app.ui.main_window import MainWindow

    window = MainWindow(admin)
    try:
        assert any(config.VENDOR_NAME in text for text in _labels(window)), \
            "اسم المزوّد غائب عن الشريط الجانبي"
    finally:
        window.deleteLater()


def test_the_settings_page_shows_it_without_a_field_to_edit(qt_app, conn, admin):
    """معروضٌ لا قابل للتحرير: لا حقل إدخال يحمل اسم المزوّد."""
    from PyQt6.QtWidgets import QLineEdit

    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    page.refresh()
    try:
        assert any(config.VENDOR_NAME in text for text in _labels(page))

        editable = [field.text() for field in page.findChildren(QLineEdit)]
        assert config.VENDOR_NAME not in editable, \
            "اسم المزوّد في حقل قابل للتحرير — يُمحى بضغطة"
    finally:
        page.deleteLater()


# ---------------------------------------------------------------------------
# غائبٌ عن الورق — وهذا هو المطلوب صراحةً
# ---------------------------------------------------------------------------
def test_the_printed_contract_never_carries_the_vendor_name(
        qt_app, conn, admin, sample_contract, tmp_path):
    """ورقة العقد تحمل اسم المكتب وحده.

    الزبون يوقّع عقداً مع المكتب الذي استأجر منه، واسمُ من كتب البرنامج على
    تلك الورقة دخيلٌ لا محلّ له.
    """
    settings_repo.set_many({
        "office_name": "مكتب النور لإيجار السيارات",
        "office_phone": "0911111111",
    }, conn=conn)

    output = tmp_path / "عقد.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    text = _pdf_text(output)
    assert "مكتب النور لإيجار السيارات" in text, "اسم المكتب غائب عن ورقته"
    assert config.VENDOR_NAME not in text, "اسم المزوّد تسرّب إلى ورقة العميل"


def test_the_contract_html_is_free_of_the_vendor_name(conn, admin, sample_contract):
    """فحصٌ على المصدر لا على الناتج وحده: النصّ نفسه خالٍ منه."""
    html = contract_pdf.build_html(sample_contract, conn=conn)
    assert config.VENDOR_NAME not in html


def test_exported_reports_are_free_of_the_vendor_name(
        conn, admin, sample_contract, tmp_path):
    """التقارير أيضاً: ترويستها هوية المكتب لا هوية من باعه البرنامج."""
    path = tmp_path / "تقرير.csv"
    reporting.export_contracts_csv(path, conn=conn)

    text = path.read_text(encoding="utf-8-sig")
    assert config.VENDOR_NAME not in text

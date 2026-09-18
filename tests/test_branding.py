# -*- coding: utf-8 -*-
"""هوية الشركة: من حقل في الإعدادات إلى ترويسة الورقة المطبوعة.

السؤال الذي يجيب عنه هذا الملف واحد: **إن غيّر صاحب الشركة اسمه أو سجلّه
التجاري في الإعدادات، هل يتغيّر ما يُطبع فعلاً؟** لأن الاسم كان مكتوباً في
ثلاثة مواضع تقرأ كلٌّ منها بطريقتها، فكان يتغيّر في ورقة ويغيب عن أخرى.

والتحقّق هنا **باستخراج نصّ الـ PDF** لا بفحص HTML: بين النصّ والورقة محرّك
طباعة كامل، وما لم يصل إلى الورقة لم يصل إلى الزبون.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtPdf import QPdfDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.repositories import settings_repo  # noqa: E402
from app.services import branding, contract_pdf  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _pdf_text(path):
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    # ``getAllText`` تُرجع ``QPdfSelection`` لا نصّاً، والنصّ في ``.text()``
    return "\n".join(document.getAllText(page).text()
                     for page in range(document.pageCount()))


# ---------------------------------------------------------------------------
# الهوية نفسها
# ---------------------------------------------------------------------------
def test_identity_reads_what_the_settings_hold(conn, admin):
    settings_repo.set_many({
        "office_name": "شركة المسار المتحد",
        "office_phone": "0911111111",
        "office_phone_alt": "0922222222",
        "office_address": "طرابلس — شارع الشط",
        "commercial_register": "TR-2024-118834",
    }, conn=conn)

    data = branding.identity(conn=conn)
    assert data["name"] == "شركة المسار المتحد"
    assert data["phone"] == "0911111111"
    assert data["phone_alt"] == "0922222222"
    assert data["address"] == "طرابلس — شارع الشط"
    assert data["commercial_register"] == "TR-2024-118834"


def test_contact_line_drops_what_is_empty(conn, admin):
    """سطر التواصل لا يطبع فاصلاً بلا ما بعده.

    مكتبٌ لم يُدخل سجلّه التجاري بعد لا يستحقّ ترويسة تنتهي بـ «— س.ت:»،
    وهي ما كانت تُنتجه صياغة تجمع الأجزاء بلا ترشيح.
    """
    settings_repo.set_many({
        "office_name": "شركة المسار المتحد",
        "office_phone": "0911111111",
        "office_phone_alt": "",
        "office_address": "",
        "commercial_register": "",
    }, conn=conn)

    line = branding.contact_line(conn=conn)
    assert line == "0911111111"
    assert "—" not in line
    assert "س.ت" not in line


def test_the_name_never_comes_out_empty(conn, admin):
    """اسمٌ مُفرَّغ في الإعدادات لا يُنتج ترويسة بلا عنوان."""
    settings_repo.set_many({"office_name": "   "}, conn=conn)
    assert branding.identity(conn=conn)["name"] == config.APP_TITLE_AR


# ---------------------------------------------------------------------------
# من الإعدادات إلى الورقة
# ---------------------------------------------------------------------------
def test_the_printed_contract_carries_the_company_identity(
        qt_app, conn, admin, sample_contract, tmp_path):
    """ما يُكتب في الإعدادات يظهر في نصّ الـ PDF نفسه."""
    settings_repo.set_many({
        "office_name": "شركة المسار المتحد",
        "office_phone": "0911111111",
        "office_address": "طرابلس — شارع الشط",
        "commercial_register": "TR-2024-118834",
    }, conn=conn)

    output = tmp_path / "عقد.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    text = _pdf_text(output)
    assert "شركة المسار المتحد" in text
    assert "0911111111" in text

    # رقم السجلّ يُفحص مقطعاً مقطعاً لا كنصّ واحد: استخراج النصّ من PDF يُعيد
    # ترتيب المقاطع اللاتينية داخل سطر عربي («TR-2024-118834» ← «-2024-118834TR»)
    # حتى مع ``dir="ltr"`` صريح — قيس ذلك بتوليد صفحة تجريبية، فهو أثر
    # الاستخراج لا أثر الطباعة. والمقصود هنا أن القيمة **وصلت الورقة**.
    for part in ("TR", "2024", "118834"):
        assert part in text, part


def test_changing_the_name_changes_the_paper(
        qt_app, conn, admin, sample_contract, tmp_path):
    """الاسم القديم يختفي من الورقة بعد تغييره — لا يبقى محفوراً في الشيفرة."""
    settings_repo.set_many({"office_name": "شركة الاسم القديم"}, conn=conn)
    first = tmp_path / "أولى.pdf"
    contract_pdf.export_pdf(sample_contract, first, force_builtin=True, conn=conn)
    assert "شركة الاسم القديم" in _pdf_text(first)

    settings_repo.set_many({"office_name": "شركة المسار المتحد"}, conn=conn)
    second = tmp_path / "ثانية.pdf"
    contract_pdf.export_pdf(sample_contract, second, force_builtin=True, conn=conn)

    text = _pdf_text(second)
    assert "شركة المسار المتحد" in text
    assert "شركة الاسم القديم" not in text


# ---------------------------------------------------------------------------
# الشعار
# ---------------------------------------------------------------------------
def _write_logo(path, color="#1d4ed8"):
    image = QImage(120, 120, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return path


def test_logo_is_copied_into_the_data_folder(qt_app, conn, admin, tmp_path):
    """يُنسخ لا يُشار إليه: الملف الأصلي قد يكون على فلاشة تُنزع."""
    source = _write_logo(tmp_path / "شعار.png")
    branding.install_logo(source)

    stored = branding.logo_path()
    assert stored is not None and stored.is_file()
    assert str(config.DATA_DIR) in str(stored)

    source.unlink()
    assert branding.logo_path() is not None, "ذهب الشعار بذهاب ملفه الأصلي"


def test_logo_reaches_the_printed_contract(
        qt_app, conn, admin, sample_contract, tmp_path):
    """العقد المطبوع بشعار أثقل من المطبوع بلا شعار — دليلٌ أنه أُدرج فعلاً."""
    without = tmp_path / "بلا.pdf"
    contract_pdf.export_pdf(sample_contract, without, force_builtin=True, conn=conn)

    branding.install_logo(_write_logo(tmp_path / "شعار.png"))
    assert branding.logo_data_uri() is not None

    with_logo = tmp_path / "بشعار.pdf"
    contract_pdf.export_pdf(sample_contract, with_logo, force_builtin=True, conn=conn)

    assert with_logo.stat().st_size > without.stat().st_size


def test_removing_the_logo_removes_the_file(qt_app, conn, admin, tmp_path):
    branding.install_logo(_write_logo(tmp_path / "شعار.png"))
    assert branding.has_logo()

    branding.remove_logo()
    assert not branding.has_logo()
    assert branding.logo_data_uri() is None


def test_a_file_that_is_not_an_image_is_refused(qt_app, conn, admin, tmp_path):
    bad = tmp_path / "ليس صورة.png"
    bad.write_text("هذا نصّ لا صورة", encoding="utf-8")

    with pytest.raises(branding.BrandingError):
        branding.install_logo(bad)


def test_an_unsupported_extension_is_refused(qt_app, conn, admin, tmp_path):
    bad = tmp_path / "ملف.txt"
    bad.write_text("x", encoding="utf-8")

    with pytest.raises(branding.BrandingError):
        branding.install_logo(bad)

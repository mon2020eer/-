# -*- coding: utf-8 -*-
"""الطباعة الصامتة وأرشفة ما يُطبع.

الاختبارات تعمل على جهاز **بلا طابعة** (كل خوادم البناء كذلك)، وهذا مقصود:
أهمّ ما يُبرهَن هنا أن غياب الطابعة **لا يُضيّع العقد** ولا يرفع خطأً — فهي
حال حاسوب المالك في بيته وحال كل جهاز تجربة.
"""

import datetime
import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.repositories import contracts_repo, settings_repo  # noqa: E402
from app.services import contract_pdf, printing  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# مجلد الأرشيف
# ---------------------------------------------------------------------------
def test_the_default_archive_is_the_exports_folder(conn, admin):
    assert printing.archive_root(conn=conn) == pathlib.Path(config.EXPORTS_DIR)


def test_the_office_can_choose_its_own_folder(conn, admin, tmp_path):
    chosen = tmp_path / "أرشيف العقود"
    printing.set_archive_root(chosen, conn=conn)

    assert printing.archive_root(conn=conn) == chosen
    assert chosen.is_dir(), "لم يُنشأ المجلد المختار"


def test_an_unusable_folder_is_refused_before_it_is_saved(conn, admin, tmp_path):
    """مسارٌ لا يصلح مجلداً يُرفض **الآن** لا عند أول طباعة.

    قبولُه هنا كان يعني اكتشاف العطب والزبون واقف ينتظر ورقته. والحالة
    المحاكاة هنا مسارٌ يمرّ عبر ملف — وهي أقرب ما يكون إلى قرص شبكة انقطع:
    الكتابة تفشل مهما كانت صلاحيات المستخدم.
    """
    a_file = tmp_path / "ملف لا مجلد.txt"
    a_file.write_text("x", encoding="utf-8")

    with pytest.raises(printing.PrintingError):
        printing.set_archive_root(a_file / "داخل الملف", conn=conn)

    # ولم يُحفظ الاختيار الفاشل: يبقى الأرشيف على مجلده السابق
    assert printing.archive_root(conn=conn) == pathlib.Path(config.EXPORTS_DIR)


def test_resetting_returns_to_the_default(conn, admin, tmp_path):
    printing.set_archive_root(tmp_path / "أرشيف", conn=conn)
    printing.set_archive_root("", conn=conn)
    assert printing.archive_root(conn=conn) == pathlib.Path(config.EXPORTS_DIR)


def test_files_are_filed_by_year_then_month(conn, admin, tmp_path):
    """مكتبٌ في سنته الثالثة لا يُفيده مجلد فيه ألف ملف."""
    printing.set_archive_root(tmp_path / "أرشيف", conn=conn)

    when = datetime.date(2026, 3, 7)
    path = printing.archive_path("CR-2026-0001.pdf", when=when, conn=conn)

    assert path.parent.name == "03"
    assert path.parent.parent.name == "2026"
    assert path.parent.is_dir()


def test_the_chosen_folder_is_really_where_the_contract_lands(
        qt_app, conn, admin, sample_contract, tmp_path):
    """الحارس الذي يربط الإعداد بالنتيجة: الملف يخرج في المجلد المختار فعلاً."""
    chosen = tmp_path / "أرشيف المكتب"
    printing.set_archive_root(chosen, conn=conn)

    contract = contracts_repo.get(sample_contract, conn=conn)
    target = printing.archive_path("%s.pdf" % contract["contract_number"], conn=conn)
    contract_pdf.export_pdf(sample_contract, target, force_builtin=True, conn=conn)

    assert target.is_file()
    assert str(chosen) in str(target)
    assert target.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# الطابعة
# ---------------------------------------------------------------------------
def test_no_printer_is_reported_not_raised(qt_app, conn, admin, sample_contract,
                                           tmp_path):
    """غياب الطابعة يُرجع ``None`` ولا يرفع استثناءً.

    لأن العقد **حُفظ**، والفرق بين «لم تُطبع» و«فشلت العملية» هو الفرق بين
    رسالة تطمئن وأخرى تُفزع صاحب المكتب على بياناته.
    """
    output = tmp_path / "عقد.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    name = printing.default_printer_name()
    if name is not None:
        pytest.skip("هذا الجهاز فيه طابعة، والحارس موضوعه غيابها")

    assert printing.print_pdf(output) is None
    assert output.is_file(), "ذهب الملف المؤرشف مع فشل الطباعة"


def test_a_missing_file_is_a_clear_arabic_error(qt_app, conn, admin, tmp_path):
    with pytest.raises(printing.PrintingError) as error:
        printing.print_pdf(tmp_path / "لا وجود له.pdf")
    assert "غير موجود" in str(error.value)


def test_a_file_that_is_not_a_pdf_is_refused(qt_app, conn, admin, tmp_path):
    if printing.default_printer_name() is None:
        pytest.skip("لا طابعة، فلا يُبلَغ موضع فحص الملف أصلاً")

    bad = tmp_path / "ليس عقداً.pdf"
    bad.write_text("هذا نصّ لا PDF", encoding="utf-8")

    with pytest.raises(printing.PrintingError):
        printing.print_pdf(bad)


def test_an_unknown_printer_name_is_refused(qt_app, conn, admin, sample_contract,
                                            tmp_path):
    output = tmp_path / "عقد.pdf"
    contract_pdf.export_pdf(sample_contract, output, force_builtin=True, conn=conn)

    with pytest.raises(printing.PrintingError):
        printing.print_pdf(output, printer_name="طابعة لا وجود لها")


def test_the_archive_setting_survives_a_restart(conn, admin, tmp_path):
    """الاختيار يُحفظ في قاعدة البيانات لا في الذاكرة."""
    chosen = tmp_path / "أرشيف دائم"
    printing.set_archive_root(chosen, conn=conn)

    stored = settings_repo.get(printing.KEY_ARCHIVE_DIR, conn=conn)
    assert stored == str(chosen)

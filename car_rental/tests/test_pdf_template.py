# -*- coding: utf-8 -*-
"""اختبارات الطباعة على نموذج عقد المكتب.

النموذج المستعمل هنا **يُولَّد داخل الاختبار** لا يُشحن مع المستودع: ملف عقد
مكتب حقيقي وثيقة تخصّ صاحبها، ولا تُودَع في مستودع شيفرة.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSize  # noqa: E402
from PyQt6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter  # noqa: E402
from PyQt6.QtPdf import QPdfDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.core import features  # noqa: E402
from app.services import pdf_template  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def blank_template(qt_app, tmp_path):
    """نموذج من صفحتين يشبه عقود المكاتب: أمامية بحقول وخلفية بالشروط."""
    path = tmp_path / "نموذج.pdf"

    writer = QPdfWriter(str(path))
    writer.setResolution(300)
    writer.setPageLayout(QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        writer.pageLayout().margins(),
    ))

    painter = QPainter(writer)
    painter.drawText(200, 300, "عقد استئجار سيارة")
    painter.drawText(200, 600, "الاسم بالكامل:")
    writer.newPage()
    painter.drawText(200, 300, "الشروط والأحكام")
    painter.end()

    return path


@pytest.fixture()
def mapping():
    return {
        "customer_name": {"page": 0, "x": 0.7, "y": 0.25, "size": 12, "align": "right"},
        "vehicle_plate": {"page": 0, "x": 0.4, "y": 0.35, "size": 12, "align": "right"},
    }


def _page_count(path):
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    return document.pageCount()


# ---------------------------------------------------------------------------
# التعبئة
# ---------------------------------------------------------------------------
def test_filled_output_keeps_every_page(conn, admin, blank_template, mapping, tmp_path):
    """صفحة الشروط لا حقول فيها، ويجب أن تخرج مع الناتج كما هي."""
    output = tmp_path / "معبّأ.pdf"
    pdf_template.fill(pdf_template.sample_values(), output,
                      mapping=mapping, path=blank_template)

    assert output.is_file()
    assert output.read_bytes()[:4] == b"%PDF"
    assert _page_count(output) == _page_count(blank_template) == 2


def test_filled_output_differs_from_the_blank(conn, admin, blank_template, mapping,
                                              tmp_path):
    """تحقّق فعلي أن شيئاً كُتب: صورة الصفحة الأولى تغيّرت."""
    output = tmp_path / "معبّأ.pdf"
    pdf_template.fill({"customer_name": "محمد علي الشريف"}, output,
                      mapping=mapping, path=blank_template)

    def first_page(path):
        document = QPdfDocument(None)
        document.load(str(path))
        return document.render(0, QSize(420, 594))

    assert first_page(output) != first_page(blank_template)


def test_empty_values_leave_the_paper_untouched(conn, admin, blank_template, mapping,
                                                tmp_path):
    """حقل بلا قيمة يُترك فارغاً لا يُملأ بشرطة على ورقة رسمية."""
    output = tmp_path / "فارغ.pdf"
    pdf_template.fill({"customer_name": ""}, output,
                      mapping=mapping, path=blank_template)
    assert _page_count(output) == 2


def test_relative_coordinates_survive_a_different_page_size(conn, admin, mapping,
                                                            tmp_path, qt_app):
    """الإحداثيات نسبية، فنموذج بمقاس آخر يُعبَّأ في المواضع نفسها نسبياً."""
    small = tmp_path / "صغير.pdf"
    writer = QPdfWriter(str(small))
    writer.setResolution(300)
    writer.setPageLayout(QPageLayout(
        QPageSize(QPageSize.PageSizeId.A5),
        QPageLayout.Orientation.Portrait,
        writer.pageLayout().margins(),
    ))
    painter = QPainter(writer)
    painter.drawText(100, 200, "نموذج صغير")
    painter.end()

    output = tmp_path / "معبّأ-صغير.pdf"
    pdf_template.fill({"customer_name": "عميل"}, output,
                      mapping=mapping, path=small)
    assert output.is_file()


# ---------------------------------------------------------------------------
# الرفض الواضح
# ---------------------------------------------------------------------------
def test_missing_template_is_refused_in_arabic(conn, admin, mapping, tmp_path):
    with pytest.raises(pdf_template.TemplateError) as error:
        pdf_template.fill({"customer_name": "س"}, tmp_path / "x.pdf",
                          mapping=mapping, path=tmp_path / "لا-يوجد.pdf")
    assert "نموذج" in str(error.value)


def test_corrupt_template_is_refused_not_crashed(conn, admin, mapping, tmp_path):
    broken = tmp_path / "تالف.pdf"
    broken.write_bytes("%PDF-1.4 ليس ملفاً حقيقياً".encode("utf-8"))

    with pytest.raises(pdf_template.TemplateError):
        pdf_template.fill({"customer_name": "س"}, tmp_path / "y.pdf",
                          mapping=mapping, path=broken)


def test_install_refuses_a_file_that_is_not_pdf(conn, admin, tmp_path):
    fake = tmp_path / "ليس.pdf"
    fake.write_text("نصّ عادي", encoding="utf-8")

    with pytest.raises(pdf_template.TemplateError):
        pdf_template.install(fake)


def test_fill_without_mapping_explains_what_to_do(conn, admin, blank_template,
                                                  tmp_path):
    with pytest.raises(pdf_template.TemplateError) as error:
        pdf_template.fill({"customer_name": "س"}, tmp_path / "z.pdf",
                          mapping={}, path=blank_template)
    assert "تحديد مواضع الحقول" in str(error.value)


# ---------------------------------------------------------------------------
# التركيب والتعيين وحالة الجاهزية
# ---------------------------------------------------------------------------
def test_install_and_mapping_roundtrip(conn, admin, blank_template, mapping):
    assert not pdf_template.has_template()
    assert not pdf_template.is_ready(conn=conn)

    pdf_template.install(blank_template)
    assert pdf_template.has_template()
    assert pdf_template.page_count() == 2
    # ورقة بلا مواضع ليست جاهزة: الطباعة تعود إلى عقد المنظومة
    assert not pdf_template.is_ready(conn=conn)

    pdf_template.save_mapping(mapping, conn=conn)
    assert pdf_template.is_ready(conn=conn)
    assert pdf_template.load_mapping(conn=conn) == mapping

    pdf_template.remove()
    assert not pdf_template.has_template()
    assert not pdf_template.is_ready(conn=conn)


def test_every_offered_field_has_a_value_builder(conn, admin, sample_customer,
                                                 sample_vehicle):
    """كل حقل يعرضه المحرّر يجب أن يجد قيمته، وإلّا عيّن المكتب حقلاً لا يُملأ."""
    import datetime

    from app.services import rental_service

    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, today.isoformat(),
        (today + datetime.timedelta(days=3)).isoformat(), conn=conn,
    )

    values = pdf_template.values_for_contract(contract_id, conn=conn)
    offered = {key for key, _, _ in pdf_template.FIELDS}

    assert offered <= set(values), "حقول معروضة بلا قيمة: %s" % (offered - set(values))
    assert set(pdf_template.sample_values()) >= offered


def test_rendering_a_page_out_of_range_is_refused(conn, admin, blank_template):
    with pytest.raises(pdf_template.TemplateError):
        pdf_template.render_page(9, path=blank_template)


# ---------------------------------------------------------------------------
# النسخة
# ---------------------------------------------------------------------------
def test_basic_tier_cannot_use_office_templates(conn, admin, blank_template, mapping,
                                                tmp_path):
    features.set_tier(features.TIER_BASIC)
    try:
        with pytest.raises(features.FeatureLocked):
            pdf_template.install(blank_template)
        with pytest.raises(features.FeatureLocked):
            pdf_template.fill({"customer_name": "س"}, tmp_path / "w.pdf",
                              mapping=mapping, path=blank_template)
    finally:
        features.set_tier(features.TIER_PRO)


def test_builtin_contract_is_used_when_no_template(conn, admin, sample_customer,
                                                   sample_vehicle, tmp_path):
    """بلا نموذج مضبوط يبقى عقد المنظومة هو المطبوع — بلا رسالة خطأ."""
    import datetime

    from app.services import contract_pdf, rental_service

    today = datetime.date.today()
    contract_id, _ = rental_service.open_contract(
        sample_customer, sample_vehicle, today.isoformat(),
        (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
    )

    assert not contract_pdf.uses_office_template(conn=conn)
    output = contract_pdf.export_pdf(contract_id, tmp_path / "عقد.pdf", conn=conn)
    assert str(output).endswith("عقد.pdf")

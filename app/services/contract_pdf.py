# -*- coding: utf-8 -*-
"""توليد عقد الإيجار وطباعته بصيغة PDF.

**لماذا Qt لا ReportLab؟** لأن ReportLab لا يُشكّل الحروف العربية ولا يصلها
تلقائياً، فيحتاج ``arabic-reshaper`` و``python-bidi`` وخطوطاً مُضمَّنة، والنتيجة
تبقى هشّة. أمّا محرّك النصوص في Qt فيدعم التشكيل العربي وثنائية الاتجاه أصلاً،
فيكفي أن نبني HTML باتجاه ``rtl`` ونطبعه.
"""

import datetime
import html

from PyQt6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QColor, QFont, QPageLayout, QPageSize, QPainter, QTextDocument,
)
from PyQt6.QtPrintSupport import QPrinter

from .. import config
from ..core import audit, money
from ..core import features
from ..repositories import contracts_repo, payments_repo, settings_repo
from . import branding, pdf_template, pricing

_STATUS_AR = config.CONTRACT_STATUS_LABELS
_PAYMENT_AR = config.PAYMENT_STATUS_LABELS
_METHOD_AR = config.PAYMENT_METHOD_LABELS


_LRM = "‎"


def _esc(value):
    return html.escape("" if value is None else str(value))


def _date(value):
    """تاريخ محاط بعلامة LRM.

    داخل مستند عربي (rtl) ينقلب «2026-09-01» بصرياً إلى «01-09-2026» لأن
    الشرطة محرف محايد. في عقد إيجار هذا ليس تشويهاً شكلياً بل تغيير لمعنى
    التاريخ، فتُثبَّت جهة القراءة صراحةً.
    """
    if value is None or value == "":
        return "—"
    return _LRM + _esc(value) + _LRM


def _ltr(value):
    """يثبّت جهة قراءة نصّ لاتيني/رقمي داخل فقرة عربية (لوحة، رقم وثيقة)."""
    if value is None or value == "":
        return "—"
    return _LRM + _esc(value) + _LRM



def _amount(minor, symbol):
    return _esc(money.format_amount(minor, symbol))


def _field(row, key, default=None):
    """قراءة عمود قد يغيب في قاعدة بيانات لم تُرقَّ بعد."""
    value = row[key] if key in row.keys() else None
    return default if value is None else value


def cancellation_stamp(contract):
    """نصّ ختم الإلغاء، أو ``None`` لعقد غير مُلغى.

    **صياغة واحدة** تُستعمل على الشاشة وعلى الورقة وفي الـ PDF. كانت الصياغة
    تُكتب في كل موضع على حدة، فاختلف ما يراه الموظّف عمّا يقرؤه الزبون على
    ورقته — وهما يتحدّثان عن العقد نفسه.

    وتاريخُ إلغاء غائب (عقدٌ أُلغي قبل هذه الترقية) لا يمنع الختم: الحالة
    «مُلغى» هي الحقيقة، والتاريخ تفصيل يُذكر إن عُرف.
    """
    if contract is None or contract["status"] != "cancelled":
        return None

    date = _field(contract, "cancelled_at") or _field(contract, "closed_at", "")
    name = _field(contract, "cancelled_by_name")

    text = "تم إلغاء العقد"
    if date:
        text += " بتاريخ %s" % str(date)[:10]
    if name:
        text += " بواسطة المستخدم %s" % name
    return text


def build_html(contract_id, conn=None):
    """يبني نصّ العقد بصيغة HTML جاهزاً للطباعة أو المعاينة."""
    contract = contracts_repo.get(contract_id, conn=conn)
    if contract is None:
        raise ValueError("العقد غير موجود.")

    payments = payments_repo.of_contract(contract_id, conn=conn)
    symbol = settings_repo.symbol_of(contract["currency_code"], conn=conn)

    # الهوية من مصدرها الوحيد: ما يُضبط في الإعدادات هو ما يُطبع على الورقة
    identity = branding.identity(conn=conn)
    logo = branding.logo_data_uri()
    logo_html = (
        '<img src="%s" style="height:64px;">' % logo if logo else ""
    )

    payment_rows = "".join(
        """<tr><td>{date}</td><td>{amount}</td><td>{method}</td><td>{note}</td></tr>""".format(
            date=_date(str(row["paid_at"])[:16]),
            amount=_amount(row["amount"], symbol),
            method=_esc(_METHOD_AR.get(row["method"], row["method"])),
            note=_esc(row["note"] or ""),
        )
        for row in payments
    ) or """<tr><td colspan="4" class="muted">لا توجد دفعات مسجَّلة على هذا العقد.</td></tr>"""

    # المدّة تُوصف بالساعات إن أُغلق العقد بالاحتساب الساعي
    hourly = _field(contract, "billing_mode") == "hourly"
    if hourly:
        duration = "%s (%s ساعة)" % (
            pricing.describe_duration(_field(contract, "hours_count", 0)),
            _field(contract, "hours_count", 0),
        )
        rate_label = "سعر الساعة"
        rate_value = _amount(_field(contract, "hourly_rate_snapshot", 0), symbol)
    else:
        duration = "%s يوم" % contract["days_count"]
        rate_label = "السعر اليومي"
        rate_value = _amount(contract["daily_rate_snapshot"], symbol)

    start_time = _field(contract, "start_time", "")
    end_time = _field(contract, "actual_end_time", "")

    stamp = cancellation_stamp(contract)
    stamp_html = (
        '<div class="cancelled">%s</div>' % _esc(stamp) if stamp else ""
    )

    return _TEMPLATE.format(
        cancelled=stamp_html,
        logo=logo_html,
        office_name=_esc(identity["name"]),
        duration=_esc(duration),
        rate_label=_esc(rate_label),
        rate_value=rate_value,
        start_time=_date(start_time) if start_time else "—",
        end_time=_date(end_time) if end_time else "—",
        office_line=_esc(branding.contact_line(conn=conn)),
        number=_esc(contract["contract_number"]),
        printed_at=_LRM + datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + _LRM,
        status=_esc(_STATUS_AR.get(contract["status"], contract["status"])),
        customer_name=_esc(contract["customer_name"]),
        customer_phone=_esc(contract["customer_phone"]),
        customer_id=_esc(contract["customer_national_id"]),
        vehicle=_esc(contract["vehicle_title"]),
        # رقم اللوحة كالتاريخ: شرطته محرف محايد ينقلبه اتجاه الفقرة العربية
        plate=_ltr(contract["plate_number"]),
        start_date=_date(contract["start_date"]),
        end_date=_date(contract["actual_end_date"] or contract["expected_end_date"]),
        end_label="تاريخ التسليم الفعلي" if contract["actual_end_date"] else "تاريخ التسليم المتوقَّع",

        subtotal=_amount(contract["subtotal"], symbol),
        discount=_amount(contract["discount"], symbol),
        extra=_amount(contract["extra_charges"], symbol),
        total=_amount(contract["total_amount"], symbol),
        paid=_amount(contract["paid_amount"], symbol),
        balance=_amount(contract["balance_due"], symbol),
        payment_status=_esc(_PAYMENT_AR.get(contract["payment_status"], "")),
        payment_rows=payment_rows,
        notes=_esc(contract["notes"] or "—"),
        start_odometer=_esc(contract["start_odometer"] if contract["start_odometer"] is not None else "—"),
        end_odometer=_esc(contract["end_odometer"] if contract["end_odometer"] is not None else "—"),
    )


def export_pdf(contract_id, output_path=None, force_builtin=False, conn=None):
    """يولّد ملف PDF للعقد ويُرجع مساره.

    إن رفع المكتب نموذج عقده وعيّن مواضع حقوله، طُبع العقد **على ورقته هو** لا
    على عقد المنظومة — فهذا ما يعرفه زبائنه ويوقّعون عليه. و``force_builtin``
    يتخطّى النموذج لمن أراد العقد المولَّد رغم وجوده.
    """
    contract = contracts_repo.get(contract_id, conn=conn)
    if contract is None:
        raise ValueError("العقد غير موجود.")

    if output_path is None:
        config.ensure_directories()
        output_path = config.EXPORTS_DIR / ("%s.pdf" % contract["contract_number"])
    output_path = str(output_path)

    if not force_builtin and uses_office_template(conn=conn):
        result = pdf_template.fill(
            pdf_template.values_for_contract(contract_id, conn=conn),
            output_path, conn=conn,
        )
        audit.log("export", "contract", contract_id,
                  {"pdf": output_path, "template": "office"}, conn=conn)
        return str(result)

    document = QTextDocument()
    document.setHtml(build_html(contract_id, conn=conn))

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(output_path)
    printer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(14, 14, 14, 14),
            QPageLayout.Unit.Millimeter,
        )
    )

    stamp = cancellation_stamp(contract)
    if stamp:
        _print_with_watermark(document, printer, stamp)
    else:
        document.setPageSize(printer.pageRect(QPrinter.Unit.Point).size())
        document.print(printer)

    audit.log("export", "contract", contract_id, {"pdf": output_path}, conn=conn)
    return output_path


# لون الختم ودرجة شفافيته. شفافٌ بما يُبقي النصّ تحته مقروءاً، وظاهرٌ بما لا
# يُخطئه من ينظر إلى الورقة — والرقمان قيسا على صفحة مولَّدة لا خُمّنا.
_WATERMARK_COLOR = QColor(185, 28, 28, 60)
_WATERMARK_ANGLE = -35


def print_paged(document, printer, on_page=None, reserve_bottom=0):
    """يطبع مستنداً صفحةً صفحة، ويستدعي ``on_page`` فوق كل صفحة بعد رسمها.

    **لماذا لا ``document.print()``؟** لأنها تفتح الرسّام وتُغلقه بنفسها، فلا
    يبقى ما يُرسم به فوق ما طُبع. وكل ما يُراد وضعه على كل صفحة — ختمُ إلغاء
    مائل، أو ترقيمُ صفحات في كشف حساب — يحتاج هذا المسار.

    ``on_page(painter, page_size, index, total)`` — والإحداثيات بالنقاط
    الطباعية (٧٢/بوصة) لأن الرسّام مقيسٌ إليها، فما يُرسم لا يتبع دقّة الطابعة.
    و``page_size`` هو **الصفحة كاملة**، لا منطقة النصّ وحدها.

    ``reserve_bottom`` شريطٌ بالنقاط يُحجز أسفل كل صفحة **فلا يصل إليه النصّ**.
    بدونه يُرسم التذييل فوق آخر سطر في الجدول فيختلط به حرفياً — قيس هذا على
    كشف حساب فخرج «صفحة ١ من ٢» مشتبكاً بأرقام آخر عقد.
    """
    # **الوحدات هي مربط الفرس.** ``document.print()`` تتكفّل بالتحويل وحدها،
    # أمّا الرسم اليدوي فيقع في بكسلات الجهاز (١٢٠٠ نقطة/بوصة)، بينما يقيس
    # المستند صفحته بالنقاط الطباعية (٧٢). فضبطُ صفحة المستند ببكسلات الجهاز
    # يجعلها في نظره صفحةً هائلة يتّسع فيها المستند كلّه، **فيخرج كل شيء على
    # ورقة واحدة** — قيس هذا فعلاً بمستند من ١٢٠ فقرة خرج صفحةً واحدة.
    #
    # فتُضبط الصفحة بالنقاط كما كانت، ويُقاس الرسّام إليها.
    page_size = printer.pageRect(QPrinter.Unit.Point).size()

    # النصّ يُصفّ في مساحة أقصر من الصفحة بمقدار الشريط المحجوز، ويبقى
    # ``page_size`` كاملاً لأن التذييل يُرسم في الشريط نفسه.
    reserve_bottom = max(0, float(reserve_bottom or 0))
    text_size = QSizeF(page_size.width(),
                       max(1.0, page_size.height() - reserve_bottom))
    document.setPageSize(text_size)
    scale = printer.resolution() / 72.0

    total = document.pageCount()

    painter = QPainter(printer)
    painter.scale(scale, scale)
    try:
        for page in range(total):
            if page:
                printer.newPage()

            # كل صفحة شريحةٌ من مستند واحد متّصل: يُزاح الرسم إلى أعلاها
            # ويُقصّ عليها، وإلّا طُبع المستند كلّه فوق كل صفحة.
            painter.save()
            painter.translate(0, -page * text_size.height())
            document.drawContents(
                painter,
                QRectF(0, page * text_size.height(),
                       text_size.width(), text_size.height()),
            )
            painter.restore()

            if on_page is not None:
                on_page(painter, page_size, page, total)
    finally:
        painter.end()


def _print_with_watermark(document, printer, text):
    """يطبع المستند وعليه ختم الإلغاء المائل فوق **كل** صفحة.

    ورقةُ عقدٍ مُلغى قد تحمل شروطها في صفحة ثانية، وختمٌ على الأولى وحدها
    يجعل الصفحة الثانية تبدو سارية إن فُصلت — ولذلك يُرسم على كل صفحة.
    """
    print_paged(
        document, printer,
        lambda painter, page_size, index, total: _draw_watermark(
            painter, page_size, text
        ),
    )


def _draw_watermark(painter, page_size, text):
    """يرسم نصّ الختم مائلاً في وسط الصفحة، مقيساً على عرضها لا بحجم ثابت."""
    painter.save()
    painter.setPen(_WATERMARK_COLOR)

    font = QFont(painter.font())
    font.setBold(True)
    # الحجم يُشتقّ من عرض الصفحة: حجمٌ ثابت بالنقاط يخرج ضئيلاً على دقّة
    # الطابعة العالية وضخماً على المنخفضة.
    font.setPixelSize(max(12, int(page_size.width() / 22)))
    painter.setFont(font)

    painter.translate(page_size.width() / 2, page_size.height() / 2)
    painter.rotate(_WATERMARK_ANGLE)

    width = page_size.width() * 1.2
    painter.drawText(
        QRectF(-width / 2, -page_size.height() / 10, width, page_size.height() / 5),
        Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
        text,
    )
    painter.restore()


# نمط الطباعة: أبيض وأسود متزن يوفّر الحبر، وحدود رمادية تُبقي الجداول مقروءة
_TEMPLATE = """<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Segoe UI', 'Tahoma', 'Arial'; font-size: 11pt; color: #111; }}
  h1 {{ font-size: 17pt; margin: 0 0 2px; }}
  h2 {{ font-size: 12pt; margin: 16px 0 6px; padding-bottom: 3px;
        border-bottom: 1.5px solid #333; }}
  .head {{ text-align: center; margin-bottom: 6px; }}
  .muted {{ color: #666; }}
  .meta {{ text-align: center; font-size: 9.5pt; color: #555; margin-bottom: 14px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 6px; }}
  th, td {{ border: 1px solid #999; padding: 5px 7px; text-align: right; font-size: 10.5pt; }}
  th {{ background: #ececec; font-weight: bold; width: 25%; }}
  .totals td {{ font-size: 11pt; }}
  .grand {{ font-weight: bold; background: #f3f3f3; }}
  .sign {{ margin-top: 34px; }}
  .sign td {{ border: none; padding-top: 30px; text-align: center; }}
  .terms {{ font-size: 9pt; color: #333; line-height: 1.7; }}
  /* ختم الإلغاء: شريط أحمر عريض أعلى الورقة. ورقةٌ مُلغاة قد تكون في يد
     الزبون بجانب ورقة سارية، فالفرق بينهما يجب أن يُرى من بعيد. */
  .cancelled {{ border: 3px solid #b91c1c; color: #b91c1c; font-size: 15pt;
                font-weight: bold; text-align: center; padding: 8px;
                margin-bottom: 10px; letter-spacing: 1px; }}
</style></head>
<body>
  {cancelled}
  <div class="head">
    {logo}
    <h1>{office_name}</h1>
    <div class="muted">{office_line}</div>
    <h1 style="font-size:14pt; margin-top:10px;">عقد إيجار سيارة</h1>
  </div>
  <div class="meta">رقم العقد: <b>{number}</b> &nbsp;|&nbsp; الحالة: {status}
    &nbsp;|&nbsp; تاريخ الطباعة: {printed_at}</div>

  <h2>بيانات المستأجر</h2>
  <table>
    <tr><th>الاسم الكامل</th><td>{customer_name}</td>
        <th>رقم الهاتف</th><td>{customer_phone}</td></tr>
    <tr><th>رقم الجواز / الرقم الوطني</th><td colspan="3">{customer_id}</td></tr>
  </table>

  <h2>بيانات السيارة</h2>
  <table>
    <tr><th>السيارة</th><td>{vehicle}</td>
        <th>رقم اللوحة</th><td>{plate}</td></tr>
    <tr><th>عدّاد الاستلام</th><td>{start_odometer}</td>
        <th>عدّاد التسليم</th><td>{end_odometer}</td></tr>
  </table>

  <h2>مدّة الإيجار والقيمة</h2>
  <table class="totals">
    <tr><th>تاريخ الاستلام</th><td>{start_date}</td>
        <th>{end_label}</th><td>{end_date}</td></tr>
    <tr><th>وقت الاستلام</th><td>{start_time}</td>
        <th>وقت التسليم</th><td>{end_time}</td></tr>
    <tr><th>المدّة المحتسَبة</th><td>{duration}</td>
        <th>{rate_label}</th><td>{rate_value}</td></tr>
    <tr><th>قيمة الإيجار</th><td>{subtotal}</td>
        <th>الخصم</th><td>{discount}</td></tr>
    <tr><th>رسوم إضافية</th><td>{extra}</td>
        <th>حالة الدفع</th><td>{payment_status}</td></tr>
    <tr class="grand"><th>الإجمالي المستحق</th><td>{total}</td>
        <th>المدفوع</th><td>{paid}</td></tr>
    <tr class="grand"><th>المتبقّي</th><td colspan="3">{balance}</td></tr>
  </table>

  <h2>الدفعات المسجَّلة</h2>
  <table>
    <tr><th style="width:22%">التاريخ</th><th style="width:22%">المبلغ</th>
        <th style="width:20%">الطريقة</th><th>ملاحظة</th></tr>
    {payment_rows}
  </table>

  <h2>ملاحظات</h2>
  <table><tr><td>{notes}</td></tr></table>

  <h2>الشروط والأحكام</h2>
  <div class="terms">
    ١. يقرّ المستأجر باستلام السيارة بحالة فنية سليمة وخالية من الأضرار الظاهرة.<br>
    ٢. يلتزم المستأجر بإعادة السيارة في التاريخ المتّفق عليه، وكل يوم تأخير يُحتسب
       بالسعر اليومي المذكور أعلاه.<br>
    ٣. المستأجر مسؤول عن كل المخالفات المرورية المسجَّلة خلال مدّة الإيجار.<br>
    ٤. لا يجوز تأجير السيارة من الباطن ولا تسليمها لقيادة شخص آخر دون إذن كتابي.<br>
    ٥. وقود السيارة على حساب المستأجر، وتُسلَّم بمستوى الوقود ذاته الذي استُلمت به.<br>
    ٦. في حال وقوع حادث يلتزم المستأجر بإبلاغ المكتب والجهات المختصّة فوراً.
  </div>

  <table class="sign">
    <tr><td>توقيع المستأجر<br><br>..............................</td>
        <td>توقيع المكتب<br><br>..............................</td></tr>
  </table>
</body></html>"""


def uses_office_template(conn=None):
    """هل يُطبع العقد على نموذج المكتب؟

    يشترط ثلاثة معاً: الميزة متاحة في النسخة، وورقة مرفوعة، ومواضع حقول
    معيَّنة عليها. نقصُ أيّها يعيد الطبع إلى عقد المنظومة بلا رسالة خطأ —
    فالمكتب يطبع عقداً صحيحاً في كل حال.
    """
    if not features.has_feature("contract_template"):
        return False
    # لا يُبتلَع فشلٌ غير متوقّع هنا: الرجوع الصامت لعقد المنظومة سلوكٌ مقصود
    # عند **غياب** النموذج أو تلفه — يفحصهما `is_ready` نفسها — لا عند عطب
    # قاعدة البيانات. ابتلاعه يجعل المكتب يظنّ أن نموذجه لم يُضبط فيعيد ضبطه
    # مراراً بلا جدوى، والسبب في مكان آخر تماماً.
    return pdf_template.is_ready(conn=conn)

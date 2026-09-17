# -*- coding: utf-8 -*-
"""توليد عقد الإيجار وطباعته بصيغة PDF.

**لماذا Qt لا ReportLab؟** لأن ReportLab لا يُشكّل الحروف العربية ولا يصلها
تلقائياً، فيحتاج ``arabic-reshaper`` و``python-bidi`` وخطوطاً مُضمَّنة، والنتيجة
تبقى هشّة. أمّا محرّك النصوص في Qt فيدعم التشكيل العربي وثنائية الاتجاه أصلاً،
فيكفي أن نبني HTML باتجاه ``rtl`` ونطبعه.
"""

import datetime
import html

from PyQt6.QtCore import QMarginsF
from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument
from PyQt6.QtPrintSupport import QPrinter

from .. import config
from ..core import audit, money
from ..core import features
from ..repositories import contracts_repo, payments_repo, settings_repo
from . import pdf_template, pricing

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


def build_html(contract_id, conn=None):
    """يبني نصّ العقد بصيغة HTML جاهزاً للطباعة أو المعاينة."""
    contract = contracts_repo.get(contract_id, conn=conn)
    if contract is None:
        raise ValueError("العقد غير موجود.")

    payments = payments_repo.of_contract(contract_id, conn=conn)
    symbol = settings_repo.symbol_of(contract["currency_code"], conn=conn)
    settings = settings_repo.all_settings(conn=conn)

    office_name = settings.get("office_name") or config.APP_TITLE_AR
    office_phone = settings.get("office_phone") or ""
    office_address = settings.get("office_address") or ""

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

    return _TEMPLATE.format(
        office_name=_esc(office_name),
        duration=_esc(duration),
        rate_label=_esc(rate_label),
        rate_value=rate_value,
        start_time=_date(start_time) if start_time else "—",
        end_time=_date(end_time) if end_time else "—",
        office_line=_esc(" — ".join(part for part in (office_address, office_phone) if part)),
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

    document.setPageSize(printer.pageRect(QPrinter.Unit.Point).size())
    document.print(printer)

    audit.log("export", "contract", contract_id, {"pdf": output_path}, conn=conn)
    return output_path


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
</style></head>
<body>
  <div class="head">
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

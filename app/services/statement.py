# -*- coding: utf-8 -*-
"""كشف حساب المبيعات: الجرد الكامل، مطبوعاً وبصيغة PDF.

**ما الذي يحلّه هذا الملف؟** كانت المنظومة تعطي أرقاماً مجمَّعة (إيراد الشهر،
المحصَّل، المتبقّي) وجداول على الشاشة. وصاحب المكتب يحتاج ما يحتاجه المحاسب:
**ورقة فيها كل عقد بسطره**، يقرؤها ويوقّعها ويحتفظ بها ويسلّمها لمحاسبه.

## الفكرة المحورية: الإيراد ليس هو النقد

هذا الالتباس هو ما يجعل صاحب المكتب يظنّ أن البرنامج يكذب عليه. مثالٌ من
أمثلته الأربعة:

    العقد الأول   ٩٠٠ د.ل، استُلمت كاملة     → إيراد ٩٠٠، نقدٌ ٩٠٠
    العقد الثاني  ٦٠٠ د.ل، أُلغي بعد عربون ١٠٠ → إيراد **صفر**، ونقدٌ **١٠٠**
    العقد الثالث  ٨٠٠ د.ل، دُفع نصفها         → إيراد ٨٠٠، نقدٌ ٤٠٠، دَينٌ ٤٠٠
    العقد الرابع  ١٠٠٠ د.ل بخصم ٢٠٠ → ٨٠٠    → إيراد ٨٠٠

فمجموع الإيراد ٢٬٥٠٠ ومجموع النقد ١٬٤٠٠، والفرق ليس خطأً: ١٬١٠٠ دَينٌ على
العملاء، و١٠٠ نقدٌ في الصندوق من عقد لا إيراد له.

**ولذلك يعرض الكشف السطرين صراحةً** ويُظهر عقود الإلغاء ومقبوضاتها في سطر
مستقلّ. كشفٌ يخفي هذا يُنتج رقمين لا يتطابقان ولا يفسّر لماذا.

## أساسان للقياس، وكلاهما في الورقة

* **أساس الاستحقاق**: عقود بدأت في الفترة، وما استُحقّ عليها. هو ما يقيس
  **عمل المكتب** في الفترة.
* **أساس النقد**: كل دفعة وقعت في الفترة أياً كان عقدها. هو ما يقيس
  **ما دخل الصندوق** فعلاً.

الخلط بينهما — وهو شائع — يجعل شهراً مزدهراً يبدو خاسراً لأن عملاءه يسدّدون
في الشهر التالي. فالورقة تسمّي كلّاً منهما باسمه.
"""

import datetime
import pathlib

from .. import config
from ..core import audit, db, features, money, session
from ..repositories import settings_repo
from . import branding, contract_pdf

_RATE = money.RATE_SCALE

# ---------------------------------------------------------------------------
# التقسيم الزمني
# ---------------------------------------------------------------------------
# (المفتاح، التسمية العربية، صيغة strftime في SQLite). المفتاح يُخزَّن ويُمرَّر،
# والتسمية تُعرض — فتغيير التسمية لا يكسر نداءً محفوظاً.
GRANULARITIES = (
    ("daily",   "يومي",   "%Y-%m-%d"),
    ("weekly",  "أسبوعي", "%Y-%W"),
    ("monthly", "شهري",   "%Y-%m"),
    ("yearly",  "سنوي",   "%Y"),
)

GRANULARITY_LABELS = {key: label for key, label, _ in GRANULARITIES}
_GRANULARITY_FORMATS = {key: fmt for key, _, fmt in GRANULARITIES}

DEFAULT_GRANULARITY = "monthly"


class StatementError(Exception):
    """خطأ في معطيات الكشف، برسالة عربية تصلح للعرض."""


def _check_period(start_date, end_date):
    """يرفض فترةً مقلوبة **قبل** توليد ورقة فارغة تُوهم أنه لا مبيعات.

    استعلامٌ بفترة مقلوبة يُرجع صفر صفوف بلا خطأ، فتخرج ورقة رسمية تقول
    «لا عقود» — وهي أسوأ من رسالة خطأ، لأنها تُصدَّق.
    """
    if not start_date or not end_date:
        raise StatementError("حدّد تاريخ البداية وتاريخ النهاية.")
    if str(start_date) > str(end_date):
        raise StatementError(
            "تاريخ البداية (%s) بعد تاريخ النهاية (%s)." % (start_date, end_date)
        )
    return str(start_date), str(end_date)


def _granularity_format(granularity):
    fmt = _GRANULARITY_FORMATS.get(granularity)
    if fmt is None:
        raise StatementError(
            "تقسيم زمني غير معروف: %s. المتاح: %s"
            % (granularity, "، ".join(GRANULARITY_LABELS.values()))
        )
    return fmt


def period_label(granularity, key):
    """تسمية عربية لمفتاح فترة كما يُخرجه ``strftime``."""
    key = str(key or "")
    if granularity == "weekly" and "-" in key:
        year, week = key.split("-", 1)
        return "الأسبوع %s من %s" % (week.lstrip("0") or "0", year)
    return key


# ---------------------------------------------------------------------------
# البيانات
# ---------------------------------------------------------------------------
@features.requires_feature("reports")
def sales_lines(start_date, end_date, conn=None):
    """سطرٌ لكل عقد في الفترة — **بما فيها الملغاة**.

    الملغاة تُعرض ولا تُحذف: صاحب المكتب يسأل «أين العقد الفلاني؟»، وكشفٌ
    يُسقطه بصمت يجعله يظنّ أن البرنامج فقد عقداً. يظهر بحالته «مُلغى»،
    ويُستثنى من مجاميع الإيراد لا من الورقة.

    ويُعاد استعمال ``v_contracts_full`` لا استعلامٌ جديد: هي أصلاً تجمع العميل
    والسيارة والرصيد المشتقّ من الدفعات، فاستعلامٌ موازٍ كان سيفترق عنها يوم
    يتغيّر أحدهما.
    """
    start_date, end_date = _check_period(start_date, end_date)
    return db.query(
        """SELECT contract_number, start_date,
                  expected_end_date, actual_end_date,
                  customer_name, customer_phone, plate_number, vehicle_title,
                  days_count, subtotal, discount, extra_charges, total_amount,
                  paid_amount, balance_due, payment_status, status,
                  currency_code, rate_to_base,
                  cancelled_at, cancelled_by_name
             FROM v_contracts_full
            WHERE start_date BETWEEN ? AND ?
            ORDER BY start_date, contract_number""",
        (start_date, end_date),
        conn=conn,
    )


@features.requires_feature("reports")
def period_totals(start_date, end_date, granularity=DEFAULT_GRANULARITY, conn=None):
    """مجاميع كل فترة فرعية (يوم/أسبوع/شهر/سنة) داخل المدى المطلوب.

    المبالغ كلّها محوَّلة إلى العملة الأساس بسعر الصرف **المحفوظ في كل عقد**،
    لا بسعر اليوم؛ فكشفُ الشهر الماضي لا يتغيّر كلّما عُدّل سعر الصرف.
    """
    start_date, end_date = _check_period(start_date, end_date)
    fmt = _granularity_format(granularity)

    return db.query(
        """SELECT strftime(?, c.start_date)                       AS period_key,
                  COUNT(*)                                        AS contracts,
                  SUM(CASE WHEN c.status = 'cancelled' THEN 1 ELSE 0 END)
                                                                  AS cancelled,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN (c.subtotal + c.extra_charges) * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS gross,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN c.discount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS discount,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN c.total_amount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS revenue,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN b.paid_amount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS collected,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN b.balance_due * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS outstanding
             FROM contracts c
             JOIN v_contract_balance b ON b.contract_id = c.id
            WHERE c.start_date BETWEEN ? AND ?
            GROUP BY period_key
            ORDER BY period_key""",
        (fmt, _RATE, _RATE, _RATE, _RATE, _RATE, start_date, end_date),
        conn=conn,
    )


@features.requires_feature("reports")
def reconciliation(start_date, end_date, conn=None):
    """الملخّص الذي **تتطابق أرقامه**: من قيمة العقود إلى النقد في الصندوق.

    كل سطر هنا مشتقٌّ لا مُدخَل، والعلاقات بينها محفوظة:

        الإجمالي        = القيمة قبل الخصم − الخصم
        المتبقّي        = الإجمالي − المحصَّل
        نقد الفترة      = كل دفعات الفترة (أساس نقدي، عقودٌ أخرى واردة)
    """
    start_date, end_date = _check_period(start_date, end_date)

    row = db.query_one(
        """SELECT COUNT(*)                                        AS contracts,
                  SUM(CASE WHEN c.status = 'cancelled' THEN 1 ELSE 0 END)
                                                                  AS cancelled_count,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN (c.subtotal + c.extra_charges) * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS gross,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN c.discount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS discount,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN c.total_amount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS revenue,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN b.paid_amount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS collected,
                  COALESCE(SUM(CASE WHEN c.status != 'cancelled'
                       THEN b.balance_due * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS outstanding,
                  COALESCE(SUM(CASE WHEN c.status = 'cancelled'
                       THEN c.total_amount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS cancelled_value,
                  COALESCE(SUM(CASE WHEN c.status = 'cancelled'
                       THEN b.paid_amount * c.rate_to_base / ?
                       ELSE 0 END), 0)                            AS cancelled_kept
             FROM contracts c
             JOIN v_contract_balance b ON b.contract_id = c.id
            WHERE c.start_date BETWEEN ? AND ?""",
        (_RATE, _RATE, _RATE, _RATE, _RATE, _RATE, _RATE, start_date, end_date),
        conn=conn,
    )

    # النقد الداخل في الفترة: **بتاريخ الدفعة** لا بتاريخ العقد. دفعةُ اليوم
    # على عقد الشهر الماضي نقدٌ دخل اليوم، وهذا ما يراه صاحب المكتب في صندوقه.
    cash_in = db.scalar(
        """SELECT COALESCE(SUM(
                    CASE WHEN p.kind = 'refund' THEN -p.amount ELSE p.amount END
                    * c.rate_to_base / ?), 0)
             FROM payments p JOIN contracts c ON c.id = p.contract_id
            WHERE date(p.paid_at) BETWEEN ? AND ?""",
        (_RATE, start_date, end_date),
        conn=conn,
        default=0,
    )

    refunds = db.scalar(
        """SELECT COALESCE(SUM(p.amount * c.rate_to_base / ?), 0)
             FROM payments p JOIN contracts c ON c.id = p.contract_id
            WHERE p.kind = 'refund' AND date(p.paid_at) BETWEEN ? AND ?""",
        (_RATE, start_date, end_date),
        conn=conn,
        default=0,
    )

    def value(key):
        return int((row[key] if row and key in row.keys() else 0) or 0)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "contracts": value("contracts"),
        "cancelled_count": value("cancelled_count"),
        "active_count": value("contracts") - value("cancelled_count"),
        "gross": value("gross"),
        "discount": value("discount"),
        "revenue": value("revenue"),
        "collected": value("collected"),
        "outstanding": value("outstanding"),
        "cancelled_value": value("cancelled_value"),
        "cancelled_kept": value("cancelled_kept"),
        "cash_in": int(cash_in),
        "refunds": int(refunds),
    }


# ---------------------------------------------------------------------------
# الورقة
# ---------------------------------------------------------------------------
_STATUS_AR = config.CONTRACT_STATUS_LABELS
_LRM = "‎"


def _esc(value):
    import html

    return html.escape("" if value is None else str(value))


def _num(value):
    """رقمٌ مثبَّت الاتجاه داخل سطر عربي.

    بلا هذا ينقلب «2026-09-18» بصرياً، وتلتبس أرقامٌ متجاورة في عمود مال —
    وهو لبسٌ لا يُحتمل في ورقة حساب.
    """
    if value in (None, ""):
        return "—"
    return _LRM + _esc(value) + _LRM


@features.requires_feature("reports")
def build_html(start_date, end_date, granularity=DEFAULT_GRANULARITY, conn=None):
    """يبني كشف الحساب بصيغة HTML جاهزاً للطباعة أو التصدير."""
    start_date, end_date = _check_period(start_date, end_date)

    lines = sales_lines(start_date, end_date, conn=conn)
    totals = period_totals(start_date, end_date, granularity, conn=conn)
    summary = reconciliation(start_date, end_date, conn=conn)

    symbol = settings_repo.base_currency(conn=conn)["symbol"]
    identity = branding.identity(conn=conn)
    logo = branding.logo_data_uri()

    def amount(minor):
        return _num(money.format_amount(minor or 0, symbol))

    # --- سطور العقود ---
    def remaining(row):
        """المتبقّي على العقد — و«—» للملغى.

        العقد المُلغى لا دَين عليه: عرضُ رصيده رقماً في عمود «المتبقّي» يجعل
        صاحب المكتب يطالب عميلاً بمال عن عقد أُلغي، ويجعل مجموع العمود يخالف
        سطر الملخّص الذي يستثنيه. والشرطة تقول الحقيقة: لا مطالبة هنا.
        """
        if row["status"] == "cancelled":
            return "—"
        return amount(row["balance_due"])

    if lines:
        line_rows = "".join(
            """<tr class="{css}">
                 <td>{number}</td><td>{date}</td><td>{customer}</td>
                 <td>{vehicle}</td><td>{gross}</td><td>{discount}</td>
                 <td>{total}</td><td>{paid}</td><td>{balance}</td>
                 <td>{status}</td>
               </tr>""".format(
                css="cancelled" if row["status"] == "cancelled" else "",
                number=_num(row["contract_number"]),
                date=_num(row["start_date"]),
                customer=_esc(row["customer_name"]),
                vehicle=_num(row["plate_number"]),
                gross=amount((row["subtotal"] or 0) + (row["extra_charges"] or 0)),
                discount=amount(row["discount"]),
                total=amount(row["total_amount"]),
                paid=amount(row["paid_amount"]),
                balance=remaining(row),
                status=_esc(_STATUS_AR.get(row["status"], row["status"])),
            )
            for row in lines
        )
    else:
        line_rows = ('<tr><td colspan="10" class="muted">'
                     'لا عقود في هذه الفترة.</td></tr>')

    # --- التجميع الدوري ---
    if totals:
        period_rows = "".join(
            """<tr><td>{period}</td><td>{count}</td><td>{cancelled}</td>
                   <td>{gross}</td><td>{discount}</td><td>{revenue}</td>
                   <td>{collected}</td><td>{outstanding}</td></tr>""".format(
                period=_num(period_label(granularity, row["period_key"])),
                count=_num(row["contracts"]),
                cancelled=_num(row["cancelled"] or 0),
                gross=amount(row["gross"]),
                discount=amount(row["discount"]),
                revenue=amount(row["revenue"]),
                collected=amount(row["collected"]),
                outstanding=amount(row["outstanding"]),
            )
            for row in totals
        )
    else:
        period_rows = ('<tr><td colspan="8" class="muted">'
                       'لا حركة في هذه الفترة.</td></tr>')

    # --- سطر عقود الإلغاء: يُعرض فقط حين يوجد ما يُفسَّر ---
    cancelled_note = ""
    if summary["cancelled_count"]:
        cancelled_note = (
            '<tr><th>عقود مُلغاة</th>'
            '<td>{count} عقداً، قيمتها {value} — <b>لا تُحتسب إيراداً</b></td></tr>'
            .format(count=_num(summary["cancelled_count"]),
                    value=amount(summary["cancelled_value"]))
        )
        if summary["cancelled_kept"]:
            cancelled_note += (
                '<tr><th>مقبوض على عقود مُلغاة</th>'
                '<td>{kept} — نقدٌ في الصندوق بلا إيراد يقابله</td></tr>'
                .format(kept=amount(summary["cancelled_kept"]))
            )

    refund_note = ""
    if summary["refunds"]:
        refund_note = (
            '<tr><th>مبالغ مُعادة للعملاء</th><td>{refunds}</td></tr>'
            .format(refunds=amount(summary["refunds"]))
        )

    return _TEMPLATE.format(
        logo='<img src="%s" style="height:56px;">' % logo if logo else "",
        office_name=_esc(identity["name"]),
        office_line=_esc(branding.contact_line(conn=conn)),
        start_date=_num(start_date),
        end_date=_num(end_date),
        granularity=_esc(GRANULARITY_LABELS.get(granularity, granularity)),
        printed_at=_num(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
        printed_by=_esc(getattr(session.current_user(), "full_name", "") or "—"),
        line_rows=line_rows,
        period_rows=period_rows,
        contracts=_num(summary["contracts"]),
        active_count=_num(summary["active_count"]),
        gross=amount(summary["gross"]),
        discount=amount(summary["discount"]),
        revenue=amount(summary["revenue"]),
        collected=amount(summary["collected"]),
        outstanding=amount(summary["outstanding"]),
        cash_in=amount(summary["cash_in"]),
        cancelled_note=cancelled_note,
        refund_note=refund_note,
    )


_TEMPLATE = """<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Segoe UI', 'Tahoma', 'Arial'; font-size: 10pt; color: #111; }}
  h1 {{ font-size: 16pt; margin: 0 0 2px; }}
  h2 {{ font-size: 11.5pt; margin: 14px 0 5px; padding-bottom: 3px;
        border-bottom: 1.5px solid #333; }}
  .head {{ text-align: center; margin-bottom: 4px; }}
  .muted {{ color: #666; text-align: center; }}
  .meta {{ text-align: center; font-size: 9pt; color: #555; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 4px; }}
  th, td {{ border: 1px solid #999; padding: 4px 5px; text-align: right;
            font-size: 9pt; }}
  th {{ background: #ececec; font-weight: bold; }}
  /* العقد الملغى يُعرض ولا يُحذف، لكنه يُميَّز فلا يُحسب سهواً ضمن الإيراد */
  tr.cancelled td {{ color: #b91c1c; background: #fdf0f0; }}
  .summary th {{ width: 42%; }}
  .summary td {{ font-size: 10pt; }}
  .grand td, .grand th {{ font-weight: bold; background: #f3f3f3; font-size: 11pt; }}
  .note {{ font-size: 8.5pt; color: #444; line-height: 1.6; margin-top: 6px; }}
  .sign td {{ border: none; padding-top: 28px; text-align: center; }}
</style></head>
<body>
  <div class="head">
    {logo}
    <h1>{office_name}</h1>
    <div class="muted">{office_line}</div>
    <h1 style="font-size:13pt; margin-top:8px;">كشف حساب المبيعات</h1>
  </div>
  <div class="meta">
    من {start_date} إلى {end_date} &nbsp;|&nbsp; التقسيم: {granularity}<br>
    أُصدر في {printed_at} بواسطة {printed_by}
  </div>

  <h2>الملخّص المالي</h2>
  <table class="summary">
    <tr><th>عدد العقود في الفترة</th><td>{contracts} — منها {active_count} سارية</td></tr>
    <tr><th>قيمة الإيجار قبل الخصم</th><td>{gross}</td></tr>
    <tr><th>الخصومات الممنوحة</th><td>{discount}</td></tr>
    <tr class="grand"><th>إجمالي إيراد العقود السارية</th><td>{revenue}</td></tr>
    <tr><th>المحصَّل من عقود الفترة</th><td>{collected}</td></tr>
    <tr class="grand"><th>المتبقّي على العملاء</th><td>{outstanding}</td></tr>
    {cancelled_note}
    {refund_note}
    <tr class="grand"><th>النقد الداخل خلال الفترة</th><td>{cash_in}</td></tr>
  </table>
  <div class="note">
    <b>الإيراد ليس هو النقد، والفرق بينهما ليس خطأً.</b>
    «إيراد العقود» ما استُحقّ على عقود بدأت في هذه الفترة، و«النقد الداخل» كل
    دفعة قُبضت فيها أياً كان عقدها — فدفعةُ اليوم على عقد الشهر الماضي نقدٌ دخل
    اليوم ولا إيراد لها اليوم. ويضاف إلى ذلك أن العقد المُلغى لا إيراد له،
    وقد يبقى عربونه في الصندوق.
  </div>

  <h2>التجميع {granularity}</h2>
  <table>
    <tr><th>الفترة</th><th>العقود</th><th>ملغاة</th><th>قبل الخصم</th>
        <th>الخصم</th><th>الإيراد</th><th>المحصَّل</th><th>المتبقّي</th></tr>
    {period_rows}
  </table>

  <h2>تفصيل العقود</h2>
  <table>
    <tr><th>رقم العقد</th><th>التاريخ</th><th>العميل</th><th>اللوحة</th>
        <th>قبل الخصم</th><th>الخصم</th><th>الإجمالي</th><th>المدفوع</th>
        <th>المتبقّي</th><th>الحالة</th></tr>
    {line_rows}
  </table>

  <table class="sign">
    <tr><td>المحاسب<br><br>..............................</td>
        <td>المدير<br><br>..............................</td></tr>
  </table>
</body></html>"""


# ---------------------------------------------------------------------------
# التصدير والطباعة
# ---------------------------------------------------------------------------
# مجلد فرعي داخل الأرشيف. كشوف الحساب تُخلط بالعقود إن شاركتها مجلدها، والمكتب
# يبحث عن كشف شهرٍ بين مئة عقد.
ARCHIVE_SUBFOLDER = "كشوفات"

# نمط اسم الملف: الفترة في الاسم نفسه، فيُعرف الكشف من قائمة الملفات بلا فتحه.
FILE_NAME_TEMPLATE = "كشف-حساب-%s-إلى-%s.pdf"

# ارتفاع شريط التذييل بالنقاط الطباعية. يُحجَز فلا يصل إليه نصّ الجدول.
FOOTER_HEIGHT = 26


def _default_output_path(start_date, end_date, conn=None):
    """مسار الكشف داخل الأرشيف: ``<الأرشيف>/كشوفات/<السنة>/``.

    يُبنى صراحةً ولا يُستدعى ``printing.archive_path``: تلك تُرجع مسار **ملف**
    داخل ``سنة/شهر``، وكشفٌ يغطّي شهرين لا شهر له يُوضع تحته. والسنة تُؤخذ من
    **بداية الفترة** لا من تاريخ اليوم، فكشفُ العام الماضي يُطبع اليوم ويُحفظ
    مع سنته لا مع سنة طباعته.
    """
    from . import printing

    year = str(start_date)[:4] or datetime.date.today().strftime("%Y")
    directory = pathlib.Path(printing.archive_root(conn=conn)) / ARCHIVE_SUBFOLDER / year
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (FILE_NAME_TEMPLATE % (start_date, end_date))


def _draw_page_number(painter, page_size, index, total):
    """يرسم «صفحة س من ص» أسفل كل صفحة.

    كشفُ شهرٍ فيه مئة عقد يتجاوز صفحات، وورقةُ حساب بلا ترقيم **تُفقد صفحةٌ
    منها بلا أن يُلاحظ أحد** — ولا شيء في الأرقام يكشف النقص.
    """
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont

    painter.save()
    painter.setPen(QColor("#555555"))

    font = QFont(painter.font())
    font.setPixelSize(9)
    painter.setFont(font)

    painter.drawText(
        QRectF(0, page_size.height() - FOOTER_HEIGHT + 6,
               page_size.width(), FOOTER_HEIGHT - 6),
        Qt.AlignmentFlag.AlignHCenter,
        # الترقيم لاتيني محاط بـ LRM: «صفحة ٢ من ١٠» تنقلب أرقامها في سياق عربي
        "صفحة %s%d من %d%s" % (_LRM, index + 1, total, _LRM),
    )
    painter.restore()


@features.requires_feature("reports")
def export_pdf(start_date, end_date, granularity=DEFAULT_GRANULARITY,
               output_path=None, conn=None):
    """يولّد كشف الحساب بصيغة PDF ويُرجع مساره.

    الافتراضي داخل مجلد الأرشيف الذي اختاره المكتب، في مجلد ``كشوفات`` فرعي —
    فالكشف يُحفظ حيث تُحفظ العقود، ولا يضيع في مجلد التنزيلات.
    """
    from PyQt6.QtCore import QMarginsF
    from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument
    from PyQt6.QtPrintSupport import QPrinter

    start_date, end_date = _check_period(start_date, end_date)

    if output_path is None:
        config.ensure_directories()
        output_path = _default_output_path(start_date, end_date, conn=conn)
    output_path = str(output_path)

    document = QTextDocument()
    document.setHtml(build_html(start_date, end_date, granularity, conn=conn))

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(output_path)
    # **أفقيّ لا عموديّ.** جدول التفصيل عشرة أعمدة مالية، وعلى A4 عمودي تنكسر
    # عناوينها داخل الخانة («المتبقّي» تخرج على ثلاثة أسطر) وتلتصق الأرقام.
    # قيس ذلك على كشف مولَّد قبل تثبيت الاتجاه.
    printer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape,
            QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter,
        )
    )

    # الطباعة اليدوية صفحةً صفحة لا ``document.print()``: هي وحدها ما يسمح
    # برسم الترقيم فوق كل صفحة بعد رسمها. والدالّة نفسها التي تطبع ختم إلغاء
    # العقود، فالمسار مبرهَنٌ باختباراتها.
    contract_pdf.print_paged(document, printer, _draw_page_number,
                             reserve_bottom=FOOTER_HEIGHT)

    audit.log("export", "statement", None,
              {"pdf": output_path, "period": "%s → %s" % (start_date, end_date),
               "granularity": granularity},
              conn=conn)
    return output_path


@features.requires_feature("reports")
def print_statement(start_date, end_date, granularity=DEFAULT_GRANULARITY,
                    output_path=None, conn=None):
    """يؤرشف الكشف ثم يطبعه صامتاً على الطابعة الافتراضية.

    يُرجع ``(المسار، اسم الطابعة)``، واسم الطابعة ``None`` حين لا طابعة على
    الجهاز — وهي **ليست حالة خطأ**: الكشف محفوظ، ويُطبع من مكانه.

    والترتيب مقصود كترتيب طباعة العقود: **الأرشفة أولاً**. كشفٌ طُبع ولم يُحفظ
    لا أثر له في المنظومة إن ضاعت ورقته.
    """
    from . import printing

    path = export_pdf(start_date, end_date, granularity,
                      output_path=output_path, conn=conn)
    return path, printing.print_pdf(path)

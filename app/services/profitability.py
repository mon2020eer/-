# -*- coding: utf-8 -*-
"""تحليل ربحية السيارات وعائد الاستثمار — «كاشف الحفر المالية».

السؤال الذي تجيب عنه هذه الوحدة سؤالٌ واحد يقرّر مصير كل سيارة في الأسطول:

    **هل هذه السيارة تكسب، أم أنّها حفرة يسقط فيها المال؟**

ولا تُجاب إلّا بجمع ثلاثة أرقام لم تكن المنظومة تجمعها معاً من قبل:

    الإيراد   = مجموع قيمة عقود السيارة غير الملغاة
    التكلفة   = مجموع دفتر تكاليفها (مصروفات مُدخَلة + تكاليف صيانة)
    الصافي    = الإيراد − التكلفة                     ← صافي الربح التشغيلي
    الاسترداد = الصافي ÷ تكلفة الشراء × ١٠٠           ← عائد الاستثمار

**قواعد محاسبية ثبّتت في هذه الوحدة عن قصد:**

1. **الإيراد تعاقدي لا نقدي.** عقدٌ سارٍ لم يُسدَّد بعد إيرادٌ للسيارة، لأن
   السؤال هنا «كم أنتجت هذه السيارة؟» لا «كم دخل الصندوق؟». ومن أراد الثاني
   فبابه كشف الحساب في صفحة التقارير.

2. **العقود الملغاة تُستثنى** — لم تُنتج ديناراً ولم تشغل السيارة يوماً.

3. **التكلفة من مصدرين لا مصدر واحد.** دفتر المصروفات الجديد **وسجلّ الصيانة
   القائم** معاً (عبر العرض ``v_vehicle_expense_ledger``). ولو حُسب الأول وحده
   لظهرت سيارةٌ أنفق المكتب على ورشتها آلافاً وكأنّها بلا تكلفة — وهو أسوأ من
   ألّا يكون في المنظومة تقرير ربحية أصلاً.

4. **كل المبالغ بالعملة الأساس.** الإيراد بلقطة سعر صرف كل عقد، والمصروفات
   بلقطة يوم صرفها؛ فلا تتبدّل أرقام الماضي كلّما عُدِّل سعر صرف اليوم.

5. **لا نسبة استرداد بلا ثمن شراء مسجَّل.** سيارةٌ لا يعرف المكتب ثمنها تُعرض
   بربحها التشغيلي وشرطةٍ مكان النسبة. رقمٌ مُختلَق هنا يُبنى عليه قرار بيع.
"""

import datetime

from ..core import db, features, money
from ..repositories import settings_repo

# ---------------------------------------------------------------------------
# استعلامات التقرير
# ---------------------------------------------------------------------------
# الاستعلام الأساس يقرأ من العرض ``v_vehicle_profitability`` المعرَّف في
# ``schema.sql``. وجودُ المعادلة في عرضٍ واحد لا مكرَّرةً في كل دالّة هو ما
# يضمن أن كل شاشة تقرأ الرقم نفسه: التقرير، وملفّ السيارة، وملفّ CSV المصدَّر.
_FLEET_SQL = """
SELECT vehicle_id, plate_number, brand, model, vehicle_title, year, color,
       status, currency_code, purchase_date, purchase_price, has_purchase_price,
       contracts_count, rented_days, total_revenue, total_expenses, net_profit
  FROM v_vehicle_profitability
"""

# أوجه الترتيب المسموحة. قائمة بيضاء لا نصّ يأتي من الواجهة: عمودُ ترتيب
# يُركَّب في SQL بلا تحقّق بابٌ مفتوح للحقن مهما بدا مصدره أليفاً.
ORDER_CLAUSES = {
    "worst":    "ORDER BY net_profit ASC, total_expenses DESC",
    "best":     "ORDER BY net_profit DESC, total_revenue DESC",
    "revenue":  "ORDER BY total_revenue DESC",
    "expenses": "ORDER BY total_expenses DESC",
    "plate":    "ORDER BY plate_number COLLATE NOCASE",
}

ORDER_LABELS = (
    ("worst", "الأسوأ أولاً (كاشف الحفر المالية)"),
    ("best", "الأعلى ربحاً أولاً"),
    ("revenue", "الأعلى إيراداً"),
    ("expenses", "الأعلى تكلفةً"),
    ("recovery", "الأقرب إلى استرداد رأس مالها"),
    ("plate", "رقم اللوحة"),
)

DEFAULT_ORDER = "worst"

# حالات الربحية — تُترجَم إلى ألوان الجدول في الواجهة
STATUS_MONEY_PIT = "money_pit"      # التكاليف تجاوزت الإيراد  ← أحمر
STATUS_RECOVERING = "recovering"    # تربح ولم تستردّ ثمنها بعد ← كهرماني
STATUS_PROFITABLE = "profitable"    # استردّت ثمنها وتربح       ← أخضر
STATUS_IDLE = "idle"                # لا عقود ولا مصروفات      ← رمادي


def classify(net_profit, purchase_price, has_purchase_price=True, has_activity=True):
    """تصنيف ربحية سيارة من أرقامها.

    * **حفرة مال**: التكاليف تجاوزت الإيراد، فالصافي سالب. هذه هي الحالة التي
      وُجد التقرير من أجل كشفها: سيارة تُشغَّل كل يوم وتُخرج من الصندوق أكثر
      ممّا تُدخل، ولا يظهر ذلك في أي تقرير إيرادات مهما دُقّق فيه.
    * **قيد الاسترداد**: تربح تشغيلياً ولم يبلغ ربحها ثمن شرائها بعد.
    * **مربحة**: استردّت ثمن شرائها كاملاً وما زاد فهو عائد صافٍ.
    * **بلا حركة**: لا عقد ولا مصروف — سيارة سُجّلت ولم تعمل بعد. تُفرَد بحالة
      خاصّة لأن صفراً في الطرفين ليس ربحاً: تلوينها أخضر يمنح المكتب طمأنينةً
      لا يقابلها دينار واحد.

    وسيارةٌ بلا ثمن شراء مسجَّل تُقاس بربحها التشغيلي وحده: موجبٌ فمربحة.
    """
    if not has_activity:
        return STATUS_IDLE
    if net_profit < 0:
        return STATUS_MONEY_PIT
    if has_purchase_price and purchase_price > 0 and net_profit < purchase_price:
        return STATUS_RECOVERING
    return STATUS_PROFITABLE


def _months_between(start_date, end_date=None):
    """عدد الأشهر بين تاريخين (شهر واحد على الأقل)، أو ``None`` إن تعذّر."""
    try:
        start = datetime.date.fromisoformat(str(start_date))
    except (TypeError, ValueError):
        return None
    end = end_date or datetime.date.today()
    months = (end.year - start.year) * 12 + (end.month - start.month)
    return max(months, 1)


def enrich(row):
    """يحوّل صفّ العرض إلى قاموس التقرير بأرقامه المشتقّة.

    المشتقّات تُحسب هنا لا في SQL لأن القسمة على صفر قرارٌ لا يحسنه العرض:
    سيارةٌ بلا ثمن شراء لا نسبة لها، لا نسبةٌ صفرية ولا لانهائية.
    """
    purchase_price = int(row["purchase_price"] or 0)
    has_price = bool(row["has_purchase_price"]) and purchase_price > 0
    revenue = int(row["total_revenue"] or 0)
    expenses = int(row["total_expenses"] or 0)
    net = int(row["net_profit"] or 0)

    # نسبة استرداد رأس المال: كم من ثمن الشراء أعادته السيارة حتى اليوم.
    # تُقاس بصافي الربح لا بالإيراد: إيرادٌ يلتهمه الإصلاح لا يستردّ شيئاً.
    recovery_ratio = None
    remaining = None
    if has_price:
        recovery_ratio = round(100.0 * net / purchase_price, 1)
        remaining = max(purchase_price - net, 0)

    # تقدير مدّة استرداد ما تبقّى بمتوسّط أداء السيارة نفسها حتى اليوم.
    # تقديرٌ لا وعد: يفترض استمرار المعدّل الحالي، ويُسكت عنه عند تعذّره.
    months_to_payback = None
    months_owned = _months_between(row["purchase_date"]) if row["purchase_date"] else None
    if remaining and months_owned and net > 0:
        monthly = net / float(months_owned)
        if monthly > 0:
            months_to_payback = int(round(remaining / monthly))

    status = classify(net, purchase_price, has_price,
                      has_activity=bool(revenue or expenses))

    return {
        # معرّف الصفّ في الجدول يُقرأ من المفتاح ``id`` (انظر DataTable.fill)
        "id": row["vehicle_id"],
        "vehicle_id": row["vehicle_id"],
        "plate_number": row["plate_number"],
        "brand": row["brand"],
        "model": row["model"],
        "vehicle_title": row["vehicle_title"],
        "year": row["year"],
        "color": row["color"],
        "status": row["status"],
        "currency_code": row["currency_code"],
        "purchase_date": row["purchase_date"],
        "purchase_price": purchase_price,
        "has_purchase_price": has_price,
        "contracts_count": int(row["contracts_count"] or 0),
        "rented_days": int(row["rented_days"] or 0),
        "total_revenue": revenue,
        "total_expenses": expenses,
        "net_profit": net,
        "recovery_ratio": recovery_ratio,
        "remaining_to_recover": remaining,
        "months_owned": months_owned,
        "months_to_payback": months_to_payback,
        "profit_status": status,
        "is_money_pit": status == STATUS_MONEY_PIT,
    }


@features.requires_feature("profitability")
def fleet_profitability(order=DEFAULT_ORDER, only_money_pits=False, conn=None):
    """ربحية كل سيارة في الأسطول — صفوف جاهزة لجدول التقرير.

    الترتيب الافتراضي «الأسوأ أولاً» عن قصد: الغرض من الشاشة أن ترى الحفرة
    المالية أوّل ما تفتحها، لا أن تبحث عنها في آخر الجدول.
    """
    clause = ORDER_CLAUSES.get(order, ORDER_CLAUSES[DEFAULT_ORDER])
    rows = [enrich(row) for row in db.query(_FLEET_SQL + clause, conn=conn)]

    # «الأقرب إلى الاسترداد» ترتيبٌ على نسبة تُحسب في بايثون، فيُطبَّق هنا.
    # وما لا نسبة له يُدفع إلى الآخر بدل أن يتصدّر بقيمة فارغة.
    if order == "recovery":
        rows.sort(key=lambda row: (row["recovery_ratio"] is None,
                                   -(row["recovery_ratio"] or 0)))

    if only_money_pits:
        rows = [row for row in rows if row["is_money_pit"]]

    return rows


@features.requires_feature("profitability")
def vehicle_profitability(vehicle_id, conn=None):
    """ربحية سيارة واحدة — يغذّي لوحة التفاصيل وملفّ السيارة."""
    row = db.query_one(
        _FLEET_SQL + "WHERE vehicle_id = ?", (vehicle_id,), conn=conn
    )
    return enrich(row) if row is not None else None


@features.requires_feature("profitability")
def expense_breakdown(vehicle_id=None, conn=None):
    """تفصيل التكاليف بأنواعها: في ماذا صُرف المال؟"""
    from ..repositories import expenses_repo

    return expenses_repo.totals_by_type(vehicle_id=vehicle_id, conn=conn)


@features.requires_feature("profitability")
def fleet_summary(conn=None):
    """ملخّص الأسطول كلّه: رأس المال، والإيراد، والتكلفة، والصافي، وعدد الحفر.

    يُحسب من الصفوف نفسها التي يعرضها الجدول لا باستعلام مستقلّ: ملخّصٌ
    يخالف مجموع ما تحته رقمان متناقضان على شاشة واحدة، وأسوأ من غياب الملخّص.
    """
    rows = fleet_profitability(conn=conn)

    invested = sum(row["purchase_price"] for row in rows if row["has_purchase_price"])
    revenue = sum(row["total_revenue"] for row in rows)
    expenses = sum(row["total_expenses"] for row in rows)
    net = revenue - expenses

    money_pits = [row for row in rows if row["is_money_pit"]]
    recovered_ratio = round(100.0 * net / invested, 1) if invested > 0 else None

    return {
        "vehicles_count": len(rows),
        "priced_count": sum(1 for row in rows if row["has_purchase_price"]),
        "invested": invested,
        "total_revenue": revenue,
        "total_expenses": expenses,
        "net_profit": net,
        "recovery_ratio": recovered_ratio,
        "money_pits_count": len(money_pits),
        "money_pits_loss": sum(row["net_profit"] for row in money_pits),
        "base_currency": settings_repo.base_currency(conn=conn)["symbol"],
    }


# ---------------------------------------------------------------------------
# التصدير
# ---------------------------------------------------------------------------
CSV_HEADERS = (
    ("vehicle_title", "السيارة"),
    ("plate_number", "رقم اللوحة"),
    ("year", "سنة الصنع"),
    ("purchase_date", "تاريخ الشراء"),
    ("purchase_price", "تكلفة الشراء"),
    ("contracts_count", "عدد العقود"),
    ("rented_days", "أيام التأجير"),
    ("total_revenue", "إجمالي الإيرادات"),
    ("total_expenses", "إجمالي المصروفات"),
    ("net_profit", "صافي الربح التشغيلي"),
    ("recovery_ratio", "نسبة استرداد رأس المال %"),
    ("remaining_to_recover", "المتبقّي لاسترداد رأس المال"),
    ("profit_status_label", "التقييم"),
)

# «المتبقّي لاسترداد رأس المال» ليس منها عمداً: سيارةٌ بلا ثمن شراء مسجَّل
# لا متبقّي لها، و``0.00`` في خانتها تُقرأ «استردّت كل شيء». فيُنسَّق يدوياً
# أدناه ليبقى فارغاً حين لا معنى له.
_MONEY_COLUMNS = ("purchase_price", "total_revenue", "total_expenses", "net_profit")


def export_profitability_csv(path, rows=None, conn=None):
    """يصدّر تقرير الربحية إلى ملف CSV يفتحه Excel العربي بلا تشويه."""
    from .. import config
    from . import reporting


    rows = rows if rows is not None else fleet_profitability(conn=conn)

    printable = []
    for row in rows:
        line = dict(row)
        line["profit_status_label"] = config.PROFIT_STATUS_LABELS.get(
            row["profit_status"], ""
        )
        # الفراغ أصدق من صفرٍ في خانة نسبةٍ لا وجود لها
        if line["recovery_ratio"] is None:
            line["recovery_ratio"] = ""
        line["remaining_to_recover"] = (
            "" if line["remaining_to_recover"] is None
            else str(money.to_major(line["remaining_to_recover"]))
        )
        printable.append(line)

    return reporting.export_rows_to_csv(
        printable, list(CSV_HEADERS), path,
        money_columns=_MONEY_COLUMNS, conn=conn,
    )

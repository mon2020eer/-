# -*- coding: utf-8 -*-
"""محرّك حساب قيمة الإيجار.

وحدة **صافية** (pure): لا تلمس قاعدة البيانات ولا الواجهة، فتُختبر وحدها
اختباراً كاملاً، وهي الموضع الوحيد الذي يُحسب فيه المال في المنظومة كلّها.

قواعد الحساب المعتمدة:

1. **عدد الأيام** = الفرق بين تاريخ التسليم وتاريخ الاستلام، وبحدّ أدنى يوم
   واحد (من يستلم ويُعيد في اليوم نفسه يدفع يوماً).
2. **السعر الأسبوعي** — إن وُجد — يُطبَّق على كل أسبوع كامل، وتُحسب الأيام
   المتبقّية بالسعر اليومي.
3. **سقف الإنصاف**: إذا كان ثمن الأيام المتبقّية أغلى من أسبوع كامل، يُحتسب
   أسبوع كامل. فلا يُعقل أن يدفع مستأجر 6 أيام أكثر من مستأجر 7 أيام.
4. الخصم يُخصم من المجموع، والرسوم الإضافية تُضاف بعده، والنتيجة لا تكون سالبة.

كل المبالغ هنا أعداد صحيحة بالوحدة الصغرى (انظر ``core/money.py``).
"""

import datetime
import math

MIN_DAYS = 1
DAYS_PER_WEEK = 7
HOURS_PER_DAY = 24
MIN_HOURS = 1

# وقت افتراضي للاستلام والتسليم حين لا يُسجَّل وقت
DEFAULT_TIME = "12:00"


def parse_date(value):
    """يقبل ``date`` أو نصاً بصيغة YYYY-MM-DD ويُرجع ``date``."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def parse_time(value):
    """يقبل ``time`` أو نصاً بصيغة HH:MM ويُرجع ``time``."""
    if isinstance(value, datetime.time):
        return value
    text = str(value or DEFAULT_TIME).strip()
    for pattern in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    return datetime.datetime.strptime(DEFAULT_TIME, "%H:%M").time()


def combine(date_value, time_value=None):
    """يدمج تاريخاً ووقتاً في ``datetime`` واحد."""
    return datetime.datetime.combine(parse_date(date_value), parse_time(time_value))


def default_hourly_rate(daily_rate):
    """سعر الساعة حين لا يُحدَّده المكتب: السعر اليومي مقسوماً على 24، مُقرَّباً لأعلى.

    التقريب لأعلى مقصود: لو قُرِّب لأسفل لخرج 24 ساعة أرخص من يوم كامل، وهو ما
    يجعل الاحتساب بالساعة ثغرةً لا تسويةً عادلة.
    """
    daily_rate = max(0, int(daily_rate or 0))
    return int(math.ceil(daily_rate / float(HOURS_PER_DAY))) if daily_rate else 0


def rental_days(start_date, end_date):
    """عدد أيام الإيجار المحتسَبة بين تاريخين، بحدّ أدنى يوم واحد."""
    start, end = parse_date(start_date), parse_date(end_date)
    if end < start:
        raise ValueError("تاريخ نهاية العقد يسبق تاريخ بدايته.")
    return max(MIN_DAYS, (end - start).days)


def base_amount(days, daily_rate, weekly_rate=0):
    """قيمة الإيجار قبل الخصم والرسوم.

    >>> base_amount(9, 10000, 60000)      # 9 أيام، 100 يومياً، 600 أسبوعياً
    80000
    """
    days = max(MIN_DAYS, int(days))
    daily_rate = max(0, int(daily_rate or 0))
    weekly_rate = max(0, int(weekly_rate or 0))

    if not weekly_rate:
        return days * daily_rate

    weeks, remainder = divmod(days, DAYS_PER_WEEK)
    total = weeks * weekly_rate + remainder * daily_rate

    # سقف الإنصاف: الأيام المتبقّية لا تتجاوز ثمن أسبوع كامل
    if remainder:
        total = min(total, (weeks + 1) * weekly_rate)

    return total


def quote(start_date, end_date, daily_rate, weekly_rate=0, discount=0, extra_charges=0):
    """يحسب تسعيرة العقد كاملة ويُرجع قاموساً بتفاصيلها.

    مفاتيح النتيجة: ``days`` و ``subtotal`` و ``discount`` و ``extra_charges``
    و ``total`` — وكلها أعداد صحيحة بالوحدة الصغرى عدا ``days``.
    """
    days = rental_days(start_date, end_date)
    subtotal = base_amount(days, daily_rate, weekly_rate)

    discount = max(0, int(discount or 0))
    extra_charges = max(0, int(extra_charges or 0))

    # الخصم لا يتجاوز قيمة الإيجار نفسها، والمجموع لا يكون سالباً أبداً
    discount = min(discount, subtotal)
    total = subtotal - discount + extra_charges

    return {
        "days": days,
        "subtotal": subtotal,
        "discount": discount,
        "extra_charges": extra_charges,
        "total": total,
    }


# ---------------------------------------------------------------------------
# الاحتساب بالساعة
# ---------------------------------------------------------------------------
def rental_hours(start_at, end_at):
    """عدد ساعات الإيجار بين وقتين، مُقرَّباً لأعلى وبحدّ أدنى ساعة.

    التقريب لأعلى لأن ساعة بدأت تُحتسب ساعة كاملة، كما هو العرف في التأجير.
    """
    if end_at < start_at:
        raise ValueError("وقت التسليم يسبق وقت الاستلام.")
    seconds = (end_at - start_at).total_seconds()
    return max(MIN_HOURS, int(math.ceil(seconds / 3600.0)))


def base_amount_hours(hours, daily_rate, weekly_rate=0, hourly_rate=0):
    """قيمة الإيجار محسوبة بالأيام الكاملة وما تبقّى بالساعة.

    القاعدة:
        أيام كاملة = الساعات ÷ 24، والباقي ساعات.
        الإجمالي = قيمة الأيام الكاملة + min(الساعات المتبقّية × سعر الساعة، سعر اليوم)

    الشقّ الأخير **سقف الإنصاف بالساعة**: ساعات الكسر لا تُكلّف أكثر من يوم كامل،
    انسجاماً مع سقف الأسبوع في ``base_amount``.

    >>> base_amount_hours(27, 24000, 0, 1000)   # يوم + 3 ساعات
    27000
    """
    hours = max(MIN_HOURS, int(hours))
    daily_rate = max(0, int(daily_rate or 0))
    hourly_rate = int(hourly_rate or 0) or default_hourly_rate(daily_rate)

    full_days, remainder = divmod(hours, HOURS_PER_DAY)

    if not remainder:
        return base_amount(full_days, daily_rate, weekly_rate)

    extra = min(remainder * hourly_rate, daily_rate)
    if not full_days:
        return extra

    return base_amount(full_days, daily_rate, weekly_rate) + extra


def quote_hours(start_at, end_at, daily_rate, weekly_rate=0, hourly_rate=0,
                discount=0, extra_charges=0):
    """تسعيرة محسوبة بالساعة. تُرجع القاموس نفسه الذي تُرجعه ``quote``
    مضافاً إليه ``hours`` و ``full_days`` و ``remainder_hours``."""
    hours = rental_hours(start_at, end_at)
    subtotal = base_amount_hours(hours, daily_rate, weekly_rate, hourly_rate)

    discount = min(max(0, int(discount or 0)), subtotal)
    extra_charges = max(0, int(extra_charges or 0))
    full_days, remainder = divmod(hours, HOURS_PER_DAY)

    return {
        "hours": hours,
        "full_days": full_days,
        "remainder_hours": remainder,
        "days": max(MIN_DAYS, full_days + (1 if remainder else 0)),
        "subtotal": subtotal,
        "discount": discount,
        "extra_charges": extra_charges,
        "total": subtotal - discount + extra_charges,
    }


def settlement(contract_row, actual_end_date, extra_charges=0,
               actual_end_time=None, hourly=False):
    """يعيد حساب العقد عند الإغلاق بالمدّة الفعلية لا المتوقَّعة.

    إن أعاد العميل السيارة متأخّراً تزيد القيمة، وإن أعادها مبكّراً تنقص —
    مع الاحتفاظ بالسعر الأصلي المحفوظ في العقد (snapshot) لا بسعر اليوم.

    ``hourly=True`` يحتسب المدّة بالساعات: يفيد في الإرجاع المبكّر حين يُعيد
    العميل السيارة قبل الموعد بساعات فلا يَعدل أن يُحاسَب بيوم كامل.
    """
    total_extra = int(contract_row["extra_charges"] or 0) + max(0, int(extra_charges or 0))

    if hourly:
        start_at = combine(contract_row["start_date"], _row_value(contract_row, "start_time"))
        end_at = combine(actual_end_date, actual_end_time)
        result = quote_hours(
            start_at, end_at,
            contract_row["daily_rate_snapshot"],
            contract_row["weekly_rate_snapshot"],
            _row_value(contract_row, "hourly_rate_snapshot", 0),
            contract_row["discount"],
            total_extra,
        )
        result["mode"] = "hourly"
    else:
        result = quote(
            contract_row["start_date"],
            actual_end_date,
            contract_row["daily_rate_snapshot"],
            contract_row["weekly_rate_snapshot"],
            contract_row["discount"],
            total_extra,
        )
        result["mode"] = "daily"
        result["hours"] = result["days"] * HOURS_PER_DAY

    result["difference"] = result["total"] - int(contract_row["total_amount"])
    return result


def _row_value(row, key, default=None):
    """قراءة متسامحة من ``sqlite3.Row`` أو من قاموس عادي (تسهّل الاختبارات)."""
    try:
        keys = row.keys()
    except AttributeError:
        keys = row
    if key in keys:
        value = row[key]
        return default if value is None else value
    return default


def arabic_count(number, one, two, few, many):
    """صياغة العدد بالعربية صياغةً سليمة.

    العربية تميّز المفرد والمثنّى وجمع القلّة (3–10) وجمع الكثرة (11 فأكثر)،
    وتجاهل ذلك يُنتج «6 ساعة» و«2 يوم» وهو ركيك في وثيقة يوقّعها عميل.

    >>> arabic_count(6, "ساعة واحدة", "ساعتان", "ساعات", "ساعة")
    '6 ساعات'
    """
    number = int(number or 0)
    if number == 1:
        return one
    if number == 2:
        return two
    if 3 <= number % 100 <= 10:
        return "%d %s" % (number, few)
    return "%d %s" % (number, many)


def describe_duration(hours):
    """وصف عربي للمدّة: «3 أيام و5 ساعات»."""
    days, remainder = divmod(int(hours or 0), HOURS_PER_DAY)
    parts = []
    if days:
        parts.append(arabic_count(days, "يوم واحد", "يومان", "أيام", "يوماً"))
    if remainder or not days:
        parts.append(arabic_count(remainder, "ساعة واحدة", "ساعتان", "ساعات", "ساعة"))
    return " و".join(parts)

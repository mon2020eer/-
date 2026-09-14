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

MIN_DAYS = 1
DAYS_PER_WEEK = 7


def parse_date(value):
    """يقبل ``date`` أو نصاً بصيغة YYYY-MM-DD ويُرجع ``date``."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


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


def settlement(contract_row, actual_end_date, extra_charges=0):
    """يعيد حساب العقد عند الإغلاق بالمدّة الفعلية لا المتوقَّعة.

    إن أعاد العميل السيارة متأخّراً تزيد القيمة، وإن أعادها مبكّراً تنقص —
    مع الاحتفاظ بالسعر الأصلي المحفوظ في العقد (snapshot) لا بسعر اليوم.
    """
    result = quote(
        contract_row["start_date"],
        actual_end_date,
        contract_row["daily_rate_snapshot"],
        contract_row["weekly_rate_snapshot"],
        contract_row["discount"],
        int(contract_row["extra_charges"] or 0) + max(0, int(extra_charges or 0)),
    )
    result["difference"] = result["total"] - int(contract_row["total_amount"])
    return result

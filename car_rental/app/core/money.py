# -*- coding: utf-8 -*-
"""التعامل مع المبالغ المالية والعملات.

**لماذا أعداد صحيحة لا فاصلة عائمة؟** لأن ``0.1 + 0.2`` في الفاصلة العائمة
لا يساوي ``0.3`` بالضبط، وتراكم هذا الخطأ في عقود ودفعات كثيرة يُنتج فروقاً
حقيقية في الحسابات. لذلك يُخزَّن كل مبلغ عدداً صحيحاً بالوحدة الصغرى
(1/100 من الوحدة الرئيسية في كل العملات المدعومة: الدينار والدولار واليورو)،
ولا يُحوَّل إلى نص إلّا لحظة العرض.

**سعر الصرف** يُخزَّن مضروباً في ``RATE_SCALE`` (مليون) لنفس السبب:
سعر 5.25 دينار للدولار يُخزَّن 5250000.
"""

from decimal import ROUND_HALF_UP, Decimal

# الوحدة الصغرى: 100 وحدة صغرى لكل وحدة رئيسية (قرش/سنت)
MINOR_UNITS = 100

# مقياس تخزين أسعار الصرف
RATE_SCALE = 1_000_000

# الأرقام العربية-الهندية للعرض الاختياري
_ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def to_minor(value):
    """يحوّل مبلغاً معروضاً (نص أو رقم) إلى عدد صحيح بالوحدة الصغرى.

    >>> to_minor("125.50")
    12550
    >>> to_minor(0)
    0
    """
    if value is None or value == "":
        return 0
    text = str(value).strip().replace(",", "").replace("٬", "")
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    amount = Decimal(text) * MINOR_UNITS
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_major(minor):
    """يحوّل الوحدة الصغرى إلى ``Decimal`` بالوحدة الرئيسية."""
    return (Decimal(int(minor or 0)) / MINOR_UNITS).quantize(Decimal("0.01"))


def format_amount(minor, symbol=None, arabic_digits=False):
    """ينسّق مبلغاً للعرض: ``1٬250.00 د.ل``.

    فاصل الآلاف يُستخدم لأن قراءة ``1250000.00`` بالعين مُرهِقة في جدول.
    """
    amount = to_major(minor)
    text = "{:,.2f}".format(amount)
    if arabic_digits:
        text = text.translate(_ARABIC_DIGITS)
    return "%s %s" % (text, symbol) if symbol else text


def rate_to_int(value):
    """يحوّل سعر صرف معروضاً (5.25) إلى تخزينه الصحيح (5250000)."""
    if value in (None, ""):
        return RATE_SCALE
    amount = Decimal(str(value)) * RATE_SCALE
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_to_display(stored):
    """العكس: من التخزين الصحيح إلى قيمة معروضة بأربع منازل."""
    return (Decimal(int(stored or RATE_SCALE)) / RATE_SCALE).quantize(Decimal("0.0001"))


def convert_to_base(minor, rate_to_base):
    """يحوّل مبلغاً بعملة العقد إلى ما يقابله بالعملة الأساس.

    يستخدم سعر الصرف **المحفوظ في العقد** لا سعر اليوم، فتبقى التقارير
    التاريخية ثابتة لا تتغيّر كلما عُدِّل سعر الصرف في الإعدادات.
    """
    return int(
        (Decimal(int(minor or 0)) * Decimal(int(rate_to_base or RATE_SCALE)) / RATE_SCALE)
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

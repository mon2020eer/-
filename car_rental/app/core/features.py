# -*- coding: utf-8 -*-
"""مزايا كل نسخة من المنظومة، والتحقّق من إتاحتها.

النسختان:

    **الأساسية** (basic): كل عمل المكتب اليومي — سيارات وعملاء وعقود (إصدار
    وتعديل وتجديد وتمديد وإنهاء) وفواتير ودفعات وحجز مسبق. بالدينار الليبي وحده.

    **المتقدّمة** (pro): ما سبق + تقارير مالية وتصدير، ونسخ احتياطي على Google
    Drive، وصيانة ومخالفات، واحتساب بالساعة، وتعدّد المستخدمين والعملات،
    وسجلّ تدقيق.

**مبدأ التقسيم:** الأساسية ليست منتجاً معطوباً — تُنجز عمل المكتب كاملاً. والمتقدّمة
تضيف ما يوفّر مالاً ووقتاً. فمن اشترى الأساسية لا يشعر بالنقص، ومن ترقّى يجد قيمة.

**وضع القفل** (locked): عند انتهاء الاشتراك. لا يُحذف شيء ولا يُحجب عن صاحب المكتب
بياناته: يقرأ ويطبع ويأخذ نسخة احتياطية كاملة، ولا ينشئ عملاً جديداً.
"""

import functools

TIER_BASIC = "basic"
TIER_PRO = "pro"
TIER_LOCKED = "locked"

TIER_LABELS = {
    TIER_BASIC: "النسخة الأساسية",
    TIER_PRO: "النسخة المتقدّمة",
    TIER_LOCKED: "الاشتراك منتهٍ",
}

# حدّ عدد السيارات في النسخة الأساسية (0 = بلا حدّ)
BASIC_VEHICLE_LIMIT = 15

# مزايا كل نسخة. الأسماء تُستعمل في @requires_feature وفي إخفاء الصفحات.
FEATURES = {
    TIER_BASIC: {
        "vehicles", "customers", "contracts", "payments", "contract_pdf",
        "dashboard", "local_backup", "settings",
    },
    TIER_PRO: {
        "vehicles", "customers", "contracts", "payments", "contract_pdf",
        "dashboard", "local_backup", "settings",
        "reports", "export", "cloud_backup", "maintenance", "violations",
        "hourly_billing", "multi_currency", "multi_user", "audit_log",
        "alerts",
    },
    # وضع القفل: قراءة وطباعة ونسخ احتياطي فقط — لا إنشاء ولا تعديل
    TIER_LOCKED: {
        "dashboard", "contract_pdf", "local_backup",
    },
}

FEATURE_LABELS = {
    "reports": "التقارير المالية",
    "export": "تصدير البيانات",
    "cloud_backup": "النسخ الاحتياطي على Google Drive",
    "maintenance": "سجلّ الصيانة",
    "violations": "المخالفات المرورية",
    "hourly_billing": "الاحتساب بالساعة",
    "multi_currency": "تعدّد العملات",
    "multi_user": "تعدّد المستخدمين",
    "audit_log": "سجلّ التدقيق",
    "alerts": "التنبيهات",
    "contracts": "إدارة العقود",
    "vehicles": "إدارة السيارات",
    "customers": "إدارة العملاء",
    "payments": "تسجيل الدفعات",
}


class FeatureLocked(Exception):
    """تُرفع عند محاولة استعمال ميزة خارج النسخة الحالية أو في وضع القفل."""


# ---------------------------------------------------------------------------
# النسخة الفعّالة
# ---------------------------------------------------------------------------
_active_tier = TIER_PRO      # الافتراض أثناء التطوير والاختبارات


def set_tier(tier):
    """يثبّت النسخة الفعّالة. يُستدعى بعد التحقّق من الترخيص عند الإقلاع."""
    global _active_tier
    if tier not in FEATURES:
        raise ValueError("نسخة غير معروفة: %s" % tier)
    _active_tier = tier
    return tier


def current_tier():
    return _active_tier


def tier_label(tier=None):
    return TIER_LABELS.get(tier or _active_tier, "")


def is_locked():
    return _active_tier == TIER_LOCKED


def has_feature(name, tier=None):
    """هل الميزة متاحة في النسخة الحالية (أو في نسخة محدّدة)؟"""
    return name in FEATURES.get(tier or _active_tier, set())


def vehicle_limit(tier=None):
    """أقصى عدد سيارات مسموح، و0 يعني بلا حدّ."""
    return BASIC_VEHICLE_LIMIT if (tier or _active_tier) == TIER_BASIC else 0


def require(name):
    """يرفع ``FeatureLocked`` إن لم تكن الميزة متاحة، برسالة عربية مفهومة."""
    if has_feature(name):
        return True

    label = FEATURE_LABELS.get(name, name)
    if is_locked():
        raise FeatureLocked(
            "انتهى اشتراكك، ولا يمكن تنفيذ عمل جديد حتى التجديد.\n"
            "بياناتك كاملة ولم يُحذف منها شيء، ويمكنك أخذ نسخة احتياطية الآن."
        )
    raise FeatureLocked(
        "«%s» متاحة في النسخة المتقدّمة فقط.\nللترقية راجع مزوّد البرنامج." % label
    )


def requires_feature(name):
    """مُزخرف يمنع تنفيذ الدالة إن كانت الميزة خارج النسخة الحالية.

    يعمل في **طبقة الخدمة** لا في الواجهة فقط، على غرار ``requires_role``:
    إخفاء زرّ إجراء تجميلي، أمّا هذا فيمنع العملية أصلاً.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            require(name)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def missing_features(tier=None):
    """المزايا الغائبة عن النسخة الحالية — تُعرض في شاشة الترقية."""
    tier = tier or _active_tier
    return sorted(FEATURES[TIER_PRO] - FEATURES.get(tier, set()))

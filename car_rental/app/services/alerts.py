# -*- coding: utf-8 -*-
"""محرّك التنبيهات: ما يوشك أن ينتهي وما انتهى فعلاً.

ثلاثة مصادر تشترك في طبيعة واحدة — **تاريخ انتهاء** يقترب أو مضى:

    • تأمين السيارة        ← مسؤولية قانونية على المكتب إن أُجّرت بلا تأمين
    • الفحص الفنّي للسيارة  ← مخالفة مرورية ومنع من السير
    • رخصة قيادة العميل     ← العمود موجود منذ الإصدار الأول ولم يكن يُستعمل

ولأنها طبيعة واحدة، فمحرّك واحد يخدمها كلّها: إضافة مصدر رابع لاحقاً (رخصة
السيارة، بطاقة الوقود) سطران في ``SOURCES`` لا وحدة جديدة.

الوحدة **صافية القراءة**: تستعلم ولا تكتب شيئاً، فتُختبر بلا واجهة.
"""

import datetime

from ..core import arabic, db, features
from ..repositories import settings_repo

# عتبة التنبيه الافتراضية: شهر يكفي لتجديد وثيقة تأمين بلا عجلة
DEFAULT_DAYS_BEFORE = 30

SETTING_KEY = "alert_days_before"

# درجات الخطورة بترتيب الإلحاح
EXPIRED = "expired"
SOON = "soon"

SEVERITY_LABELS = {
    EXPIRED: "منتهٍ",
    SOON: "يوشك",
}

KIND_LABELS = {
    "insurance": "تأمين السيارة",
    "inspection": "الفحص الفنّي",
    "license": "رخصة قيادة العميل",
}


class Alert(object):
    """تنبيه واحد جاهز للعرض وللقرار."""

    __slots__ = ("kind", "severity", "subject", "subject_id", "expiry_date",
                 "days_left", "detail")

    def __init__(self, kind, severity, subject, subject_id, expiry_date,
                 days_left, detail=""):
        self.kind = kind
        self.severity = severity
        self.subject = subject
        self.subject_id = subject_id
        self.expiry_date = expiry_date
        self.days_left = days_left
        self.detail = detail

    @property
    def kind_label(self):
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def severity_label(self):
        return SEVERITY_LABELS.get(self.severity, self.severity)

    @property
    def message(self):
        """نصّ عربي مكتمل يصلح للعرض في شريط أو جدول أو حوار."""
        if self.severity == EXPIRED:
            days = abs(self.days_left)
            return "%s لـ%s انتهى منذ %s (%s)." % (
                self.kind_label, self.subject, arabic.days(days), self.expiry_date
            )
        return "%s لـ%s ينتهي بعد %s (%s)." % (
            self.kind_label, self.subject, arabic.days(self.days_left), self.expiry_date
        )

    def __repr__(self):  # pragma: no cover - للتشخيص فقط
        return "<Alert %s/%s %s %+d>" % (
            self.kind, self.severity, self.subject, self.days_left
        )


# (النوع، الجدول، عمود التاريخ، عمود الاسم، شرط إضافي)
SOURCES = (
    ("insurance", "vehicles", "insurance_expiry",
     "brand || ' ' || model || ' — ' || plate_number", None),
    ("inspection", "vehicles", "inspection_expiry",
     "brand || ' ' || model || ' — ' || plate_number", None),
    ("license", "customers", "license_expiry",
     "full_name", "is_blacklisted = 0"),
)


def days_before(conn=None):
    """عتبة التنبيه من الإعدادات، وبحدّ أدنى يوم واحد."""
    value = settings_repo.get_int(SETTING_KEY, DEFAULT_DAYS_BEFORE, conn=conn)
    return max(1, int(value or DEFAULT_DAYS_BEFORE))


def _parse(value):
    try:
        return datetime.datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def collect(today=None, threshold=None, kinds=None, conn=None):
    """يجمع التنبيهات من كل المصادر مرتَّبةً بالأشدّ إلحاحاً أولاً.

    ``threshold`` عدد الأيام قبل الانتهاء؛ يُقرأ من الإعدادات إن لم يُمرَّر.
    ``kinds`` يحصر الأنواع المطلوبة.
    """
    features.require("alerts")

    today = today or datetime.date.today()
    limit = days_before(conn=conn) if threshold is None else max(1, int(threshold))
    wanted = set(kinds) if kinds else None

    found = []
    for kind, table, column, name_expr, extra in SOURCES:
        if wanted is not None and kind not in wanted:
            continue

        where = "%s IS NOT NULL AND %s <> ''" % (column, column)
        if extra:
            where += " AND " + extra

        rows = db.query(
            "SELECT id, %s AS subject, %s AS expiry FROM %s WHERE %s"
            % (name_expr, column, table, where),
            conn=conn,
        )

        for row in rows:
            expiry = _parse(row["expiry"])
            if expiry is None:
                continue                     # تاريخ مشوّه لا يُنتج تنبيهاً كاذباً

            days_left = (expiry - today).days
            if days_left < 0:
                severity = EXPIRED
            elif days_left <= limit:
                severity = SOON
            else:
                continue                     # ما زال بعيداً: لا يُزعج المستخدم

            found.append(Alert(
                kind=kind,
                severity=severity,
                subject=row["subject"],
                subject_id=row["id"],
                expiry_date=str(row["expiry"]),
                days_left=days_left,
            ))

    # المنتهي قبل الموشك، والأقرب انتهاءً قبل الأبعد
    found.sort(key=lambda alert: (alert.severity != EXPIRED, alert.days_left))
    return found


def summary(today=None, conn=None):
    """عدّادات سريعة للوحة المعلومات بلا تفصيل."""
    alerts = collect(today=today, conn=conn)
    return {
        "total": len(alerts),
        "expired": sum(1 for alert in alerts if alert.severity == EXPIRED),
        "soon": sum(1 for alert in alerts if alert.severity == SOON),
    }


def vehicle_insurance_state(vehicle_row, today=None):
    """حالة تأمين سيارة بعينها — يُستعمل عند فتح عقد.

    لا يمرّ بـ ``features.require`` لأنه فحص على صفّ في اليد لا استعلام مزايا:
    تحذير المكتب من تأجير سيارة بلا تأمين لا يُباع بالاشتراك.
    """
    today = today or datetime.date.today()
    value = (vehicle_row["insurance_expiry"]
             if "insurance_expiry" in vehicle_row.keys() else None)

    expiry = _parse(value)
    if expiry is None:
        return None

    days_left = (expiry - today).days
    if days_left >= 0:
        return None

    return Alert(
        kind="insurance", severity=EXPIRED,
        subject="%s %s — %s" % (vehicle_row["brand"], vehicle_row["model"],
                                vehicle_row["plate_number"]),
        subject_id=vehicle_row["id"],
        expiry_date=expiry.isoformat(),
        days_left=days_left,
    )

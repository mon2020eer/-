# -*- coding: utf-8 -*-
"""خدمة الاشتراك: تربط الترخيص بقاعدة البيانات وبمزايا النسخة.

المسؤوليات:
    • قراءة المفتاح المحفوظ وفحصه عند كل إقلاع.
    • بدء الفترة التجريبية عند أول اختيار لنسخة.
    • كشف إرجاع ساعة الجهاز.
    • تثبيت النسخة الفعّالة في ``core/features`` فتُطبَّق على التطبيق كلّه.
"""

import datetime
import json
import pathlib
import uuid

from ..core import audit, features, licensing
from ..repositories import settings_repo

# مفاتيح الإعدادات
KEY_LICENSE = "license_key"
KEY_TRIAL_START = "trial_started_on"
KEY_TRIAL_TIER = "trial_tier"
KEY_LAST_SEEN = "last_seen_date"


def _today():
    return datetime.date.today()


# ---------------------------------------------------------------------------
# وسم التجربة: خارج قاعدة البيانات لأن القاعدة تُستبدل
# ---------------------------------------------------------------------------
# «تجربة واحدة لكل جهاز» وعدٌ لا تستطيع قاعدةُ البيانات حفظه: ``--data-dir``
# و``CAR_RENTAL_HOME`` يختاران قاعدةً أخرى، فقاعدة جديدة = تجربة جديدة بلا حدّ.
# فيُكتب الوسم في ملفّ في مجلد المستخدم، مربوطاً ببصمة الجهاز.
#
# وحدّه معروف ومقصود التصريح به: هذا يمنع التجاوز **العرضي** — مكتب يجرّب ثم
# ينشئ قاعدة جديدة فيجد التجربة منتهية — ولا يمنع عابثاً مصمِّماً يملك جهازه
# ويحذف الملف. والنموذج العامل دون إنترنت لا يملك تخزيناً محصَّناً أصلاً، فادّعاء
# غير ذلك خداعٌ للنفس. وحاجزُ الجِدّ كافٍ: من يبلغ حذفَ ملفٍّ مخفيّ لم يكن
# ليدفع أصلاً.
_MARKER_NAME = ".car_rental_trial"


def _trial_marker_path():
    """مسار وسم التجربة — في مجلد المستخدم لا في مجلد بيانات التطبيق."""
    return pathlib.Path.home() / _MARKER_NAME


def _read_trial_marker():
    """يقرأ وسم التجربة إن كان لهذا الجهاز، وإلّا ``None``.

    وسمٌ منسوخ من جهاز آخر (مع ملفّات المستخدم مثلاً) يُهمل: لا يجوز أن
    يُحرَم مكتبٌ من تجربته لأن ملفّاً غريباً وصل إلى حاسوبه.
    """
    try:
        raw = _trial_marker_path().read_text(encoding="utf-8")
        marker = json.loads(raw)
    except (OSError, ValueError):
        return None

    if not isinstance(marker, dict) or not marker.get("started"):
        return None
    if marker.get("fingerprint") != machine_id():
        return None
    return marker


def _write_trial_marker(started, tier):
    """يكتب وسم التجربة، ويصمت إن تعذّرت الكتابة.

    فشل الكتابة — مجلد للقراءة فقط، أو صلاحية محجوبة — لا يجوز أن يمنع مكتباً
    من تجربة البرنامج: الوسم حمايةٌ للمالك، والتجربة خدمةٌ للعميل، ولا تُلغى
    الخدمة لأن الحماية تعذّرت.
    """
    try:
        _trial_marker_path().write_text(
            json.dumps({"fingerprint": machine_id(), "started": started, "tier": tier},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def machine_id():
    """بصمة هذا الجهاز — يرسلها العميل عند الشراء."""
    return licensing.machine_fingerprint()


def saved_key(conn=None):
    return settings_repo.get(KEY_LICENSE, "", conn=conn)


def status(conn=None, today=None):
    """يفحص حالة الاشتراك الحالية ويُرجع ``LicenseStatus``.

    ترتيب الفحص: تلاعب الساعة ← مفتاح محفوظ ← فترة تجريبية ← لا شيء.
    """
    today = today or _today()

    # 1) تلاعب بالساعة يُبطل كل شيء: لا اشتراك ولا تجربة
    last_seen = settings_repo.get(KEY_LAST_SEEN, "", conn=conn)
    if licensing.clock_was_rolled_back(last_seen, today):
        return licensing.LicenseStatus(
            features.TIER_LOCKED, "invalid",
            message="تاريخ الجهاز غير متّسق مع آخر تشغيل.\n"
                    "اضبط تاريخ الجهاز الصحيح، أو أدخل مفتاح اشتراك ساري.",
        )

    # 2) مفتاح محفوظ
    key = saved_key(conn=conn)
    if key:
        try:
            return licensing.check_key(key, today=today)
        except licensing.LicenseError as error:
            return licensing.LicenseStatus(
                features.TIER_LOCKED, "invalid", message=str(error)
            )

    # 3) فترة تجريبية — من القاعدة، أو من وسم الجهاز إن استُبدلت القاعدة
    started = settings_repo.get(KEY_TRIAL_START, "", conn=conn)
    tier = settings_repo.get(KEY_TRIAL_TIER, features.TIER_BASIC, conn=conn)
    if not started:
        marker = _read_trial_marker()
        if marker:
            started = marker["started"]
            tier = marker.get("tier") or features.TIER_BASIC
    if started:
        return licensing.trial_status(started, tier, today=today)

    # 4) لم يُختر شيء بعد
    return licensing.LicenseStatus(
        features.TIER_LOCKED, "none",
        message="اختر النسخة التي تريد تجربتها للبدء.",
    )


def start_trial(tier, conn=None, today=None):
    """يبدأ الفترة التجريبية بالنسخة المختارة — مرّة واحدة فقط لكل جهاز."""
    if tier not in (features.TIER_BASIC, features.TIER_PRO):
        raise ValueError("نسخة غير معروفة.")

    if settings_repo.get(KEY_TRIAL_START, "", conn=conn) or _read_trial_marker():
        raise licensing.LicenseError(
            "سبق استعمال الفترة التجريبية على هذا الجهاز.\n"
            "للمتابعة أدخل مفتاح اشتراك."
        )

    today = today or _today()
    settings_repo.set_value(KEY_TRIAL_START, today.isoformat(), conn=conn)
    settings_repo.set_value(KEY_TRIAL_TIER, tier, conn=conn)
    settings_repo.set_value(KEY_LAST_SEEN, today.isoformat(), conn=conn)
    _write_trial_marker(today.isoformat(), tier)

    audit.log("create", "settings", details={"trial": tier}, conn=conn)
    return apply_status(status(conn=conn, today=today))


def activate(key, conn=None, today=None):
    """يحفظ مفتاح اشتراك بعد التحقّق منه، ويُرجع الحالة الجديدة."""
    result = licensing.check_key(key, today=today or _today())

    if result.state == "invalid":
        raise licensing.LicenseError(result.message)
    if result.state == "expired":
        raise licensing.LicenseError(result.message)

    settings_repo.set_value(KEY_LICENSE, key.strip(), conn=conn)
    settings_repo.set_value(KEY_LAST_SEEN, (today or _today()).isoformat(), conn=conn)

    audit.log("update", "settings",
              details={"license": result.license_id, "tier": result.tier}, conn=conn)
    return apply_status(result)


def apply_status(result):
    """يثبّت النسخة الفعّالة في ``features`` ويُرجع الحالة كما هي."""
    features.set_tier(result.tier if result.is_usable else features.TIER_LOCKED)
    return result


def touch(conn=None, today=None):
    """يسجّل «آخر يوم شُوهد» — أساس كشف إرجاع الساعة."""
    today = (today or _today()).isoformat()
    last_seen = settings_repo.get(KEY_LAST_SEEN, "", conn=conn)
    if today > (last_seen or ""):
        settings_repo.set_value(KEY_LAST_SEEN, today, conn=conn)
    return today


def boot(conn=None, today=None):
    """يُستدعى عند إقلاع التطبيق: يفحص، يثبّت النسخة، يسجّل آخر تشغيل."""
    result = apply_status(status(conn=conn, today=today))
    if result.is_usable:
        touch(conn=conn, today=today)
    return result


def deactivate(conn=None):
    """يحذف المفتاح المحفوظ — يُستعمل عند نقل الترخيص إلى جهاز آخر."""
    settings_repo.set_value(KEY_LICENSE, "", conn=conn)
    audit.log("update", "settings", details={"license": "removed"}, conn=conn)
    return apply_status(status(conn=conn))


def new_license_id():
    """رقم ترخيص قصير للتوليد والتتبّع."""
    return uuid.uuid4().hex[:10].upper()

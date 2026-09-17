# -*- coding: utf-8 -*-
"""الترخيص والاشتراك الشهري.

**المشكلة:** مكاتب الإيجار قد لا تكون متصلة بالإنترنت، فلا يصلح خادم تحقّق.
والحلّ مفتاح **موقَّع رقمياً** يحمل بيانات الاشتراك داخله ويُتحقَّق منه محلياً.

**صيغة المفتاح:**

    CR-<حمولة JSON بـ base64url>.<توقيع Ed25519 بـ base64url>

الحمولة تحمل: جهة الاشتراك · النسخة · تاريخ الانتهاء · بصمة الجهاز · رقم الترخيص.

**لماذا Ed25519؟** التوقيع بمفتاح خاص يبقى عند مالك البرنامج وحده، والتطبيق يحمل
**المفتاح العام فقط**. فمن فكّ التطبيق كلّه لا يستطيع توليد مفتاح صالح، لأن التوليد
يحتاج ما ليس في التطبيق أصلاً.

**جهاز واحد:** الحمولة تحمل بصمة الجهاز، فالمفتاح لا يعمل على جهاز آخر.

**مصارحة:** أي برنامج يعمل على جهاز العميل قابل للتعديل بمن يملك المهارة والوقت؛
التوقيع يمنع **توليد** المفاتيح لا تعديل البرنامج نفسه. الحماية العملية الحقيقية
هي التحديثات والدعم اللذان لا تحصل عليهما النسخة المعدَّلة.
"""

import base64
import datetime
import hashlib
import json
import os
import platform
import subprocess
import uuid

from . import arabic

KEY_PREFIX = "CR-"
TRIAL_DAYS = 7

# مفتاح التوقيع العام (Raw Ed25519, 32 بايت بـ base64url).
#
# يُترك فارغاً في المستودع عمداً: كل من يبيع نسخة يولّد زوج مفاتيحه الخاص عبر
#     python tools/license_tool.py --init
# ثم يضع المفتاح العام هنا ويعيد البناء. لو وُضع مفتاح جاهز في المستودع لصار
# مفتاحاً خاصاً معروفاً للجميع، ولاستطاع أي أحد توليد اشتراكات مجانية.
PLACEHOLDER_KEY = "REPLACE_WITH_YOUR_PUBLIC_KEY"

PUBLIC_KEY_B64 = os.environ.get("CAR_RENTAL_PUBLIC_KEY", PLACEHOLDER_KEY)


def is_configured(public_key_b64=None):
    """هل وُضع مفتاح التوقيع العام في هذه النسخة؟"""
    key = public_key_b64 or PUBLIC_KEY_B64
    return bool(key) and key != PLACEHOLDER_KEY


class LicenseError(Exception):
    """خطأ ترخيص برسالة عربية جاهزة للعرض."""


# ---------------------------------------------------------------------------
# بصمة الجهاز
# ---------------------------------------------------------------------------
def _windows_machine_id():
    """UUID اللوحة الأمّ من ويندوز — أثبت المعرّفات وأقلّها تغيّراً."""
    try:
        output = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode("utf-8", "ignore")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) > 1 and lines[1].lower() not in ("", "uuid"):
            return lines[1]
    except Exception:
        pass

    # بديل عبر PowerShell حين يغيب wmic (ويندوز 11 الحديث)
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
            stderr=subprocess.DEVNULL, timeout=15,
        ).decode("utf-8", "ignore").strip()
        if output:
            return output
    except Exception:
        pass

    return None


def _linux_machine_id():
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
                if value:
                    return value
        except OSError:
            continue
    return None


def machine_fingerprint():
    """بصمة ثابتة لهذا الجهاز.

    **المعرّف الأقوى وحده** حين يتوفّر (UUID اللوحة الأمّ في ويندوز، و
    ``machine-id`` في لينكس)، والمصادر المتغيّرة **بديلاً عند غيابه لا مزيجاً
    معه**.

    التمييز ليس تفصيلاً: مزجُ اسم الجهاز وعنوان MAC مع المعرّف الثابت يجعل أي
    تغيير عارض — اسم حاسوب يُصحَّح، بطاقة شبكة تُستبدل — يبطل مفتاح عميل دافع
    فيُحرَم من برنامجه بلا ذنب، ويتحمّل المالك مكالمةَ غضبٍ وإصدارَ مفتاح جديد.
    وأمّا الحماية فلا تنقص: المعرّف الثابت وحده لا يُنسخ إلى جهاز آخر.

    ولا تُكشف أرقام الجهاز الحقيقية للعميل: يُعرض تجزيء لا المعرّف نفسه.
    """
    stable = (_windows_machine_id() if platform.system() == "Windows"
              else _linux_machine_id())

    if stable and stable.strip():
        parts = [stable]
    else:
        # لا معرّف ثابت: تُجمع المصادر المتاحة مهما تكن، فبصمةٌ قابلة للتغيّر
        # خيرٌ من لا بصمة — وهذه الحالة نادرة أصلاً.
        parts = [platform.node() or "", platform.machine() or "", str(uuid.getnode())]

    raw = "|".join(part.strip().lower() for part in parts if part)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    # يُعرض للعميل ليرسله عند الشراء: مجموعات من أربعة محارف
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------------------
# ترميز الحمولة والتحقّق من التوقيع
# ---------------------------------------------------------------------------
def _b64encode(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def encode_payload(payload):
    """يحوّل قاموس الحمولة إلى نصّ مُرمَّز ثابت الترتيب (ليتطابق التوقيع)."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return _b64encode(raw)


def decode_key(key):
    """يفصل المفتاح إلى (حمولة، توقيع) دون التحقّق منه."""
    key = (key or "").strip().replace(" ", "").replace("\n", "")
    if not key.startswith(KEY_PREFIX):
        raise LicenseError("صيغة المفتاح غير صحيحة.")

    body = key[len(KEY_PREFIX):]
    if "." not in body:
        raise LicenseError("صيغة المفتاح غير صحيحة.")

    encoded, signature = body.rsplit(".", 1)
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except Exception:
        raise LicenseError("المفتاح تالف أو غير مكتمل.")

    return payload, encoded, signature


def verify_signature(encoded_payload, signature, public_key_b64=None):
    """يتحقّق من توقيع Ed25519. يُرجع True/False ولا يرفع استثناء."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError:
        raise LicenseError(
            "مكتبة التحقّق غير مثبَّتة. أعد تثبيت البرنامج من المصدر الرسمي."
        )

    key_text = public_key_b64 or PUBLIC_KEY_B64
    if not is_configured(key_text):
        raise LicenseError(
            "لم يُضبط مفتاح التوقيع في هذه النسخة من البرنامج.\n"
            "على مزوّد البرنامج تشغيل: python tools/license_tool.py --init"
        )

    try:
        public_key = Ed25519PublicKey.from_public_bytes(_b64decode(key_text))
        public_key.verify(_b64decode(signature), encoded_payload.encode("ascii"))
    except InvalidSignature:
        return False
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# حالة الترخيص
# ---------------------------------------------------------------------------
class LicenseStatus(object):
    """نتيجة فحص الترخيص، جاهزة للعرض وللقرار."""

    __slots__ = ("tier", "office", "expires_on", "days_left", "state", "message",
                 "license_id")

    def __init__(self, tier, state, office="", expires_on=None, days_left=0,
                 message="", license_id=""):
        self.tier = tier
        self.state = state          # trial | active | expired | invalid | none
        self.office = office
        self.expires_on = expires_on
        self.days_left = days_left
        self.message = message
        self.license_id = license_id

    @property
    def is_usable(self):
        return self.state in ("trial", "active")

    @property
    def is_expiring_soon(self):
        return self.is_usable and 0 <= self.days_left <= 5

    def __repr__(self):  # pragma: no cover - للتشخيص فقط
        return "<LicenseStatus %s/%s %d يوم>" % (self.tier, self.state, self.days_left)


def _today():
    return datetime.date.today()


def _parse_date(value):
    return datetime.datetime.strptime(str(value), "%Y-%m-%d").date()


def check_key(key, fingerprint=None, public_key_b64=None, today=None):
    """يفحص مفتاحاً ويُرجع ``LicenseStatus``.

    الترتيب مقصود: التوقيع أولاً (فالحمولة غير موثوقة قبله)، ثم الجهاز، ثم التاريخ.
    """
    today = today or _today()
    fingerprint = fingerprint or machine_fingerprint()

    payload, encoded, signature = decode_key(key)

    if not verify_signature(encoded, signature, public_key_b64):
        return LicenseStatus(
            features_locked_tier(), "invalid",
            message="المفتاح غير صالح أو مُعدَّل. تأكّد من نسخه كاملاً.",
        )

    tier = payload.get("tier")
    if tier not in ("basic", "pro"):
        return LicenseStatus(features_locked_tier(), "invalid",
                             message="نوع النسخة في المفتاح غير معروف.")

    machine = payload.get("machine")
    if machine and machine != fingerprint:
        return LicenseStatus(
            features_locked_tier(), "invalid",
            message="هذا المفتاح صادر لجهاز آخر.\nبصمة هذا الجهاز: %s" % fingerprint,
        )

    try:
        expires_on = _parse_date(payload.get("expires"))
    except (ValueError, TypeError):
        return LicenseStatus(features_locked_tier(), "invalid",
                             message="تاريخ الانتهاء في المفتاح غير صالح.")

    days_left = (expires_on - today).days
    office = payload.get("office", "")
    license_id = payload.get("id", "")

    if days_left < 0:
        return LicenseStatus(
            features_locked_tier(), "expired", office, expires_on, days_left,
            "انتهى اشتراكك بتاريخ %s. جدّد للمتابعة." % expires_on.isoformat(),
            license_id,
        )

    return LicenseStatus(
        tier, "active", office, expires_on, days_left,
        "الاشتراك فعّال حتى %s." % expires_on.isoformat(), license_id,
    )


def features_locked_tier():
    """يُرجع اسم وضع القفل — دالة لتفادي استيراد دائري مع ``features``."""
    return "locked"


# ---------------------------------------------------------------------------
# التجربة المجانية وكشف التلاعب بالساعة
# ---------------------------------------------------------------------------
def trial_status(started_on, tier, today=None):
    """حالة التجربة المجانية بحسب تاريخ بدايتها."""
    today = today or _today()
    try:
        started = _parse_date(started_on)
    except (ValueError, TypeError):
        return LicenseStatus(features_locked_tier(), "none",
                             message="لم تُفعَّل أي نسخة بعد.")

    expires_on = started + datetime.timedelta(days=TRIAL_DAYS)
    days_left = (expires_on - today).days

    if days_left < 0:
        return LicenseStatus(
            features_locked_tier(), "expired", expires_on=expires_on,
            days_left=days_left,
            message="انتهت الفترة التجريبية (%s). للمتابعة اشترك."
                    % arabic.days(TRIAL_DAYS),
        )

    return LicenseStatus(
        tier, "trial", expires_on=expires_on, days_left=days_left,
        message="فترة تجريبية: تبقّى %s." % arabic.days(max(days_left, 0)),
    )


def clock_was_rolled_back(last_seen, today=None):
    """هل أُرجعت ساعة الجهاز إلى الوراء؟

    أسهل طرق التحايل على اشتراك يعمل بلا إنترنت هي تأخير تاريخ الجهاز. يُخزَّن
    آخر تاريخ شُوهد، فإن صار «اليوم» أسبق منه فالساعة عُبث بها.
    السماح بيوم واحد يتفادى فروق المناطق الزمنية وتعديلات الوقت العادية.
    """
    if not last_seen:
        return False
    try:
        seen = _parse_date(last_seen)
    except (ValueError, TypeError):
        return False
    return (today or _today()) < seen - datetime.timedelta(days=1)

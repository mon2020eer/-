# -*- coding: utf-8 -*-
"""اختبارات الترخيص: التوقيع وبصمة الجهاز والانتهاء وكشف التلاعب بالساعة.

الاختبارات تولّد **زوج مفاتيح خاصاً بها** ولا تستعمل مفتاح الإنتاج إطلاقاً،
فتعمل في أي بيئة ولا تكشف سرّاً.
"""

import base64
import datetime

import pytest

from app.core import features, licensing
from app.services import subscription


# ---------------------------------------------------------------------------
# أدوات: زوج مفاتيح للاختبار وإصدار مفاتيح موقَّعة
# ---------------------------------------------------------------------------
def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.fixture(scope="module")
def keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_b64 = _b64(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    )
    return private_key, public_b64


def _issue(keypair, machine="TEST-MACHINE", tier="pro", days=30, office="مكتب الاختبار",
           today=None):
    """يُصدر مفتاحاً موقَّعاً كما تفعل أداة المالك تماماً."""
    private_key, _ = keypair
    start = today or datetime.date.today()
    payload = {
        "id": "TEST123456",
        "office": office,
        "tier": tier,
        "machine": machine,
        "issued": start.isoformat(),
        "expires": (start + datetime.timedelta(days=days)).isoformat(),
    }
    encoded = licensing.encode_payload(payload)
    signature = _b64(private_key.sign(encoded.encode("ascii")))
    return "%s%s.%s" % (licensing.KEY_PREFIX, encoded, signature)


# ---------------------------------------------------------------------------
# بصمة الجهاز
# ---------------------------------------------------------------------------
def test_fingerprint_is_stable_and_formatted():
    first = licensing.machine_fingerprint()
    second = licensing.machine_fingerprint()

    assert first == second                    # ثابتة بين الاستدعاءات
    assert len(first.split("-")) == 4         # مجموعات تُقرأ وتُملى بالهاتف
    assert first.isupper()


# ---------------------------------------------------------------------------
# التحقّق من المفاتيح
# ---------------------------------------------------------------------------
def test_valid_key_is_accepted(keypair):
    key = _issue(keypair)
    result = licensing.check_key(key, fingerprint="TEST-MACHINE",
                                 public_key_b64=keypair[1])

    assert result.state == "active"
    assert result.tier == "pro"
    assert result.office == "مكتب الاختبار"
    assert result.is_usable
    assert result.days_left == 30


def test_tampered_key_is_rejected(keypair):
    """تغيير محرف واحد في المفتاح يُبطله — هذا جوهر التوقيع."""
    key = _issue(keypair)
    tampered = key[:-2] + ("A" if key[-2] != "A" else "B") + key[-1]

    result = licensing.check_key(tampered, fingerprint="TEST-MACHINE",
                                 public_key_b64=keypair[1])
    assert result.state == "invalid"
    assert not result.is_usable


def test_payload_cannot_be_edited_to_extend_subscription(keypair):
    """تمديد تاريخ الانتهاء يدوياً في الحمولة يُكشف، لأن التوقيع لا يطابقها."""
    import json

    key = _issue(keypair, days=1)
    payload, encoded, signature = licensing.decode_key(key)

    payload["expires"] = "2099-12-31"          # محاولة التحايل
    forged_encoded = licensing.encode_payload(payload)
    forged = "%s%s.%s" % (licensing.KEY_PREFIX, forged_encoded, signature)

    result = licensing.check_key(forged, fingerprint="TEST-MACHINE",
                                 public_key_b64=keypair[1])
    assert result.state == "invalid"
    assert json.loads  # يُبقي الاستيراد مستعملاً


def test_key_for_another_machine_is_rejected(keypair):
    """جهاز واحد فقط: المفتاح لا يعمل على غير جهازه."""
    key = _issue(keypair, machine="MACHINE-A")
    result = licensing.check_key(key, fingerprint="MACHINE-B",
                                 public_key_b64=keypair[1])

    assert result.state == "invalid"
    assert "جهاز آخر" in result.message


def test_expired_key_is_rejected(keypair):
    yesterday = datetime.date.today() - datetime.timedelta(days=40)
    key = _issue(keypair, days=30, today=yesterday)

    result = licensing.check_key(key, fingerprint="TEST-MACHINE",
                                 public_key_b64=keypair[1])
    assert result.state == "expired"
    assert not result.is_usable
    assert result.tier == features.TIER_LOCKED


def test_key_from_a_different_signer_is_rejected(keypair):
    """مفتاح وقّعه أحد غير مالك البرنامج لا يُقبل."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    attacker = (Ed25519PrivateKey.generate(), keypair[1])
    key = _issue(attacker)          # يوقّعه المهاجم، ويُفحص بمفتاحنا العام

    result = licensing.check_key(key, fingerprint="TEST-MACHINE",
                                 public_key_b64=keypair[1])
    assert result.state == "invalid"


def test_expiring_soon_is_flagged(keypair):
    key = _issue(keypair, days=3)
    result = licensing.check_key(key, fingerprint="TEST-MACHINE",
                                 public_key_b64=keypair[1])
    assert result.is_expiring_soon


def test_malformed_keys_do_not_crash(keypair):
    for bad in ("", "غير-صالح", "CR-", "CR-abc", "XX-abc.def"):
        with pytest.raises(licensing.LicenseError):
            licensing.decode_key(bad)


def test_unconfigured_build_says_so_clearly():
    """نسخة لم يُوضع فيها مفتاح التوقيع تُخبر بذلك بدل رسالة غامضة."""
    assert not licensing.is_configured(licensing.PLACEHOLDER_KEY)
    with pytest.raises(licensing.LicenseError) as error:
        licensing.verify_signature("x", "y", licensing.PLACEHOLDER_KEY)
    assert "مفتاح التوقيع" in str(error.value)


# ---------------------------------------------------------------------------
# الفترة التجريبية
# ---------------------------------------------------------------------------
def test_trial_runs_then_expires():
    started = datetime.date(2026, 1, 1)

    during = licensing.trial_status(started.isoformat(), "pro",
                                    today=started + datetime.timedelta(days=3))
    assert during.state == "trial"
    assert during.tier == "pro"
    assert during.days_left == 4

    after = licensing.trial_status(
        started.isoformat(), "pro",
        today=started + datetime.timedelta(days=licensing.TRIAL_DAYS + 1),
    )
    assert after.state == "expired"
    assert after.tier == features.TIER_LOCKED


# ---------------------------------------------------------------------------
# كشف إرجاع الساعة
# ---------------------------------------------------------------------------
def test_clock_rollback_is_detected():
    seen = datetime.date(2026, 6, 10)
    assert licensing.clock_was_rolled_back(seen.isoformat(), datetime.date(2026, 5, 1))
    assert not licensing.clock_was_rolled_back(seen.isoformat(), datetime.date(2026, 6, 11))
    # فرق يوم واحد مقبول: مناطق زمنية وتعديلات وقت عادية
    assert not licensing.clock_was_rolled_back(seen.isoformat(), datetime.date(2026, 6, 9))
    assert not licensing.clock_was_rolled_back("", datetime.date(2020, 1, 1))


# ---------------------------------------------------------------------------
# خدمة الاشتراك مع قاعدة البيانات
# ---------------------------------------------------------------------------
def test_new_install_has_no_subscription(conn, admin):
    result = subscription.status(conn=conn)
    assert result.state == "none"
    assert not result.is_usable


def test_trial_can_be_started_once(conn, admin):
    result = subscription.start_trial(features.TIER_BASIC, conn=conn)
    assert result.state == "trial"
    assert result.tier == features.TIER_BASIC
    assert features.current_tier() == features.TIER_BASIC

    with pytest.raises(licensing.LicenseError):
        subscription.start_trial(features.TIER_PRO, conn=conn)


def test_activation_applies_the_tier(conn, admin, keypair, monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", keypair[1])
    monkeypatch.setattr(licensing, "machine_fingerprint", lambda: "TEST-MACHINE")

    key = _issue(keypair, tier="pro")
    result = subscription.activate(key, conn=conn)

    assert result.state == "active"
    assert features.current_tier() == features.TIER_PRO
    assert subscription.saved_key(conn=conn) == key


def test_expired_key_is_not_saved(conn, admin, keypair, monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", keypair[1])
    monkeypatch.setattr(licensing, "machine_fingerprint", lambda: "TEST-MACHINE")

    old = datetime.date.today() - datetime.timedelta(days=60)
    key = _issue(keypair, days=30, today=old)

    with pytest.raises(licensing.LicenseError):
        subscription.activate(key, conn=conn)
    assert subscription.saved_key(conn=conn) == ""


def test_boot_locks_when_clock_is_rolled_back(conn, admin, keypair, monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", keypair[1])
    monkeypatch.setattr(licensing, "machine_fingerprint", lambda: "TEST-MACHINE")

    subscription.activate(_issue(keypair), conn=conn)
    subscription.touch(conn=conn, today=datetime.date(2026, 6, 10))

    result = subscription.boot(conn=conn, today=datetime.date(2026, 5, 1))

    assert result.state == "invalid"
    assert features.current_tier() == features.TIER_LOCKED
    assert "تاريخ الجهاز" in result.message


def test_transfer_removes_the_key(conn, admin, keypair, monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", keypair[1])
    monkeypatch.setattr(licensing, "machine_fingerprint", lambda: "TEST-MACHINE")

    subscription.activate(_issue(keypair), conn=conn)
    subscription.deactivate(conn=conn)

    assert subscription.saved_key(conn=conn) == ""
    assert features.current_tier() == features.TIER_LOCKED

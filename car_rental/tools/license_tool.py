# -*- coding: utf-8 -*-
"""أداة توليد مفاتيح الاشتراك — **لمالك البرنامج وحده، لا تُوزَّع مع التطبيق**.

المفتاح الخاص هو رأس مالك: من يملكه يولّد اشتراكات مجانية للأبد. احفظه خارج
المستودع وخذ منه نسخة احتياطية؛ ضياعه يعني أن كل المفاتيح الصادرة تبقى صالحة
لكنك لا تستطيع إصدار جديد إلّا بمفتاح جديد وتحديث للتطبيق.

الاستخدام:

    # مرّة واحدة: توليد زوج المفاتيح
    python tools/license_tool.py --init

    # بصمة الجهاز (يرسلها العميل إليك)
    python tools/license_tool.py --machine-id

    # إصدار اشتراك شهر لمكتب على جهازه
    python tools/license_tool.py --office "مكتب النور" --tier basic \\
        --months 1 --machine A1B2-C3D4-E5F6-7890

    # التحقّق من مفتاح أصدرته
    python tools/license_tool.py --verify CR-xxxx.yyyy --machine A1B2-...
"""

import argparse
import datetime
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.core import licensing  # noqa: E402

PRIVATE_KEY_FILE = pathlib.Path.home() / ".car_rental_license_private.key"
ISSUED_LOG = pathlib.Path(__file__).resolve().parent / "issued_licenses.jsonl"


def _b64(raw):
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text):
    import base64

    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------------------
def init_keys(force=False):
    """يولّد زوج مفاتيح Ed25519 جديداً."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if PRIVATE_KEY_FILE.exists() and not force:
        print("⚠ يوجد مفتاح خاص بالفعل في: %s" % PRIVATE_KEY_FILE)
        print("  استعمل --init --force لاستبداله (سيُبطل قدرتك على إصدار مفاتيح متوافقة).")
        return 1

    private_key = Ed25519PrivateKey.generate()
    raw_private = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    raw_public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    PRIVATE_KEY_FILE.write_text(_b64(raw_private), encoding="utf-8")
    try:
        PRIVATE_KEY_FILE.chmod(0o600)
    except OSError:
        pass

    public_b64 = _b64(raw_public)

    print("✅ تولّد زوج المفاتيح.")
    print("\nالمفتاح الخاص (سرّي — لا تشاركه أبداً):")
    print("  %s" % PRIVATE_KEY_FILE)
    print("\nالمفتاح العام — ضعه في app/core/licensing.py مكان PUBLIC_KEY_B64:")
    print("\n  PUBLIC_KEY_B64 = \"%s\"\n" % public_b64)
    print("ثم أعد بناء التطبيق. بدون هذه الخطوة لن يقبل التطبيق أي مفتاح.")
    return 0


def _load_private_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not PRIVATE_KEY_FILE.exists():
        raise SystemExit(
            "✗ لا يوجد مفتاح خاص. شغّل أولاً: python tools/license_tool.py --init"
        )
    raw = _unb64(PRIVATE_KEY_FILE.read_text(encoding="utf-8").strip())
    return Ed25519PrivateKey.from_private_bytes(raw)


def issue(office, tier, months, machine, days=None, note=""):
    """يُصدر مفتاح اشتراك موقَّعاً ويطبعه."""
    private_key = _load_private_key()

    start = datetime.date.today()
    if days:
        expires = start + datetime.timedelta(days=int(days))
    else:
        # الشهر = 30 يوماً: بسيط ومفهوم للعميل ولا يحتاج تقويماً
        expires = start + datetime.timedelta(days=30 * int(months))

    payload = {
        "id": _new_id(),
        "office": office,
        "tier": tier,
        "machine": machine,
        "issued": start.isoformat(),
        "expires": expires.isoformat(),
    }

    encoded = licensing.encode_payload(payload)
    signature = _b64(private_key.sign(encoded.encode("ascii")))
    key = "%s%s.%s" % (licensing.KEY_PREFIX, encoded, signature)

    _log_issued(payload, key, note)

    print("=" * 68)
    print("  الجهة      : %s" % office)
    print("  النسخة     : %s" % ("الأساسية" if tier == "basic" else "المتقدّمة"))
    print("  الجهاز     : %s" % machine)
    print("  يبدأ       : %s" % start.isoformat())
    print("  ينتهي      : %s  (%d يوماً)" % (expires.isoformat(), (expires - start).days))
    print("  رقم الترخيص: %s" % payload["id"])
    print("=" * 68)
    print("\nالمفتاح — أرسله للعميل كما هو:\n")
    print(key)
    print()
    return 0


def _new_id():
    import uuid

    return uuid.uuid4().hex[:10].upper()


def _log_issued(payload, key, note):
    """سجلّ بكل مفتاح صدر — أساس متابعة الاشتراكات والتجديدات."""
    record = dict(payload)
    record["note"] = note
    record["key"] = key
    with open(ISSUED_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def verify(key, machine=None):
    """يفحص مفتاحاً كما يفحصه التطبيق تماماً."""
    public_b64 = os.environ.get("CAR_RENTAL_PUBLIC_KEY")
    if not public_b64 and PRIVATE_KEY_FILE.exists():
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        private_key = Ed25519PrivateKey.from_private_bytes(
            _unb64(PRIVATE_KEY_FILE.read_text(encoding="utf-8").strip())
        )
        public_b64 = _b64(
            private_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        )

    result = licensing.check_key(
        key, fingerprint=machine or licensing.machine_fingerprint(),
        public_key_b64=public_b64,
    )

    print("الحالة     : %s" % result.state)
    print("النسخة     : %s" % result.tier)
    print("الجهة      : %s" % (result.office or "—"))
    print("ينتهي      : %s" % (result.expires_on or "—"))
    print("المتبقّي    : %s يوم" % result.days_left)
    print("الرسالة    : %s" % result.message)
    return 0 if result.is_usable else 1


def upcoming_renewals(days=7):
    """الاشتراكات التي تنتهي قريباً — لتذكير العملاء قبل التوقّف."""
    if not ISSUED_LOG.exists():
        print("لا يوجد سجلّ إصدارات بعد.")
        return 0

    today = datetime.date.today()
    limit = today + datetime.timedelta(days=int(days))
    rows = []

    with open(ISSUED_LOG, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                expires = datetime.datetime.strptime(record["expires"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if today <= expires <= limit:
                rows.append((expires, record))

    if not rows:
        print("لا اشتراكات تنتهي خلال %d أيام." % days)
        return 0

    print("اشتراكات تنتهي خلال %d أيام:\n" % days)
    for expires, record in sorted(rows):
        print("  %s  %-25s %-8s  (تبقّى %d يوم)" % (
            expires.isoformat(), record.get("office", "—"),
            record.get("tier", "—"), (expires - today).days,
        ))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="أداة إدارة مفاتيح اشتراك منظومة إيجار السيارات"
    )
    parser.add_argument("--init", action="store_true", help="توليد زوج مفاتيح جديد")
    parser.add_argument("--force", action="store_true", help="استبدال المفتاح الخاص")
    parser.add_argument("--machine-id", action="store_true",
                        help="طباعة بصمة هذا الجهاز")
    parser.add_argument("--office", help="اسم المكتب المشترك")
    parser.add_argument("--tier", choices=["basic", "pro"], help="النسخة")
    parser.add_argument("--months", type=int, default=1, help="عدد الأشهر (30 يوماً لكل شهر)")
    parser.add_argument("--days", type=int, help="عدد أيام صريح بدل الأشهر")
    parser.add_argument("--machine", help="بصمة جهاز العميل")
    parser.add_argument("--note", default="", help="ملاحظة تُحفظ في السجل")
    parser.add_argument("--verify", help="التحقّق من مفتاح")
    parser.add_argument("--renewals", type=int, nargs="?", const=7,
                        help="الاشتراكات المنتهية خلال N يوماً (افتراضياً 7)")

    args = parser.parse_args(argv)

    if args.init:
        return init_keys(force=args.force)

    if args.machine_id:
        print(licensing.machine_fingerprint())
        return 0

    if args.verify:
        return verify(args.verify, args.machine)

    if args.renewals is not None:
        return upcoming_renewals(args.renewals)

    if args.office and args.tier and args.machine:
        return issue(args.office, args.tier, args.months, args.machine,
                     args.days, args.note)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

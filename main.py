# -*- coding: utf-8 -*-
"""نقطة تشغيل مراقب مناقصات السفر والسياحة على منصة العطاءات الحكومية الليبية.

أمثلة الاستخدام:
    python main.py                 # التشغيل المعتاد: فحص وإرسال التنبيهات
    python main.py --dry-run       # فحص وطباعة النتائج دون إرسال أي رسالة
    python main.py --chat-id       # استخراج رقم المحادثة (chat_id) من بوتك
    python main.py --test-message  # رسالة اختبارية للتأكّد من وصول التنبيهات
"""

import argparse
import datetime
import sys
import time

from tender_watcher import notifier, portal
from tender_watcher.config import Settings
from tender_watcher.matcher import filter_tenders
from tender_watcher.state import SeenStore


def _print(message):
    """طباعة متوافقة مع سجلّ GitHub Actions."""
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def show_chat_id(token):
    """يعرض رقم المحادثة لكل من راسل البوت، وهي أسهل طريقة للحصول عليه."""
    import requests

    if not token:
        _print("✋ يلزم ضبط المتغيّر TELEGRAM_BOT_TOKEN أولاً.")
        return 1

    url = notifier.TELEGRAM_API.format(token=token, method="getUpdates")
    data = requests.get(url, timeout=30).json()

    if not data.get("ok"):
        _print("❌ الرمز غير صحيح. راجع الرمز الذي منحك إيّاه BotFather.")
        return 1

    chats = {}
    for update in data.get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id"):
            name = chat.get("title") or " ".join(
                filter(None, [chat.get("first_name"), chat.get("last_name")])
            ) or chat.get("username") or "بدون اسم"
            chats[chat["id"]] = name

    if not chats:
        _print("ℹ️ لم تصل أي رسالة بعد. افتح محادثة البوت على هاتفك وأرسل /start ثم أعد المحاولة.")
        return 1

    _print("✅ أرقام المحادثات المتاحة (ضع الرقم في السرّ TELEGRAM_CHAT_ID):")
    for chat_id, name in chats.items():
        _print("   TELEGRAM_CHAT_ID = %s   ← %s" % (chat_id, name))
    return 0


def run(settings, dry_run=False):
    """الدورة الكاملة: جلب ← ترشيح ← استبعاد المُرسَل سابقاً ← إرسال ← حفظ الحالة."""
    _print("⏳ جارٍ جلب الإعلانات من منصة العطاءات الحكومية…")
    tenders = portal.fetch_tenders(settings)
    _print("📥 تم جلب %d إعلاناً." % len(tenders))

    matches = filter_tenders(tenders, settings)
    _print("🎯 عدد الإعلانات المطابقة لكلماتك المفتاحية: %d" % len(matches))

    store = SeenStore(str(settings.state_file))
    fresh = [m for m in matches if m.tender_id not in store]
    _print("🆕 المطابق والجديد (لم يُرسَل سابقاً): %d" % len(fresh))

    if dry_run:
        for match in matches:
            _print("\n" + "-" * 60)
            _print("النتيجة: %d | %s" % (match.score, match.title))
            _print("الجهة: %s | النشر: %s" % (match.entity, match.date))
            _print("الكلمات: %s" % "، ".join(sorted(set(match.title_hits) | set(match.body_hits))))
            _print("الرابط: %s" % match.url)
        _print("\n🧪 وضع الاختبار: لم تُرسَل أي رسالة.")
        return 0

    missing = settings.validate()
    if missing:
        _print("✋ أسرار ناقصة: %s" % "، ".join(missing))
        return 1

    telegram = notifier.TelegramNotifier(
        settings.telegram_token, settings.telegram_chat_id,
        timeout=settings.request_timeout, max_retries=settings.max_retries,
    )

    if store.is_first_run:
        # التشغيل الأول: ملخّص + أحدث النتائج فقط، تفادياً لإرسال الأرشيف كاملاً
        limit = settings.first_run_alert_limit
        _print("🚀 التشغيل الأول: سيُرسل ملخّص وأحدث %d إعلان." % limit)
        telegram.send(notifier.format_summary(matches, len(tenders)))
        to_send = fresh[:limit]
    else:
        to_send = fresh[: settings.max_alerts_per_run]

    for index, match in enumerate(to_send, start=1):
        telegram.send(notifier.format_tender(match))
        _print("   ✅ (%d/%d) %s" % (index, len(to_send), match.title[:60]))
        if index < len(to_send):
            time.sleep(1)  # مباعدة بسيطة احتراماً لحدود معدّل تيليجرام

    # تُسجَّل كل المطابقات كمقروءة، حتى ما تجاوز سقف الإرسال، لمنع التكرار لاحقاً
    store.add_many([m.tender_id for m in matches])
    store.save(datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", len(tenders))
    _print("💾 تم حفظ الحالة في %s" % settings.state_file)
    _print("🏁 اكتمل التشغيل بنجاح.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="مراقبة مناقصات السفر والسياحة على منصة العطاءات الحكومية الليبية"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="فحص وطباعة النتائج دون إرسال أي رسالة")
    parser.add_argument("--chat-id", action="store_true",
                        help="استخراج رقم المحادثة chat_id من البوت")
    parser.add_argument("--test-message", action="store_true",
                        help="إرسال رسالة اختبارية للتأكّد من الإعداد")
    args = parser.parse_args()

    settings = Settings()

    if args.chat_id:
        return show_chat_id(settings.telegram_token)

    if args.test_message:
        missing = settings.validate()
        if missing:
            _print("✋ أسرار ناقصة: %s" % "، ".join(missing))
            return 1
        notifier.TelegramNotifier(
            settings.telegram_token, settings.telegram_chat_id
        ).send("✅ <b>تم ربط بوت مناقصات السفر والسياحة بنجاح.</b>\nالإعداد سليم والتنبيهات ستصلك تلقائياً.")
        _print("✅ أُرسلت الرسالة الاختبارية. تحقّق من هاتفك.")
        return 0

    try:
        return run(settings, dry_run=args.dry_run)
    except portal.PortalError as error:
        _print("❌ %s" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""إرسال التنبيهات إلى هاتفك عبر واجهة بوت تيليجرام."""

import html
import time

import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# تيليجرام يرفض أي رسالة تتجاوز 4096 محرفاً
_MAX_MESSAGE = 3900


class TelegramNotifier(object):
    """غلاف بسيط حول طريقة sendMessage مع إعادة المحاولة واحترام حدود المعدّل."""

    def __init__(self, token, chat_id, timeout=30, max_retries=4):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _call(self, method, payload):
        url = TELEGRAM_API.format(token=self.token, method=method)
        delay = 2
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(url, json=payload, timeout=self.timeout)
                # 429 تعني تجاوز حدّ المعدّل، وتيليجرام يحدّد مدّة الانتظار
                if response.status_code == 429:
                    retry_after = response.json().get("parameters", {}).get("retry_after", delay)
                    time.sleep(int(retry_after) + 1)
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2

        raise RuntimeError("فشل إرسال رسالة تيليجرام: %s" % last_error)

    def send(self, text):
        """يرسل رسالة واحدة بتنسيق HTML مع تعطيل معاينة الروابط."""
        return self._call("sendMessage", {
            "chat_id": self.chat_id,
            "text": text[:_MAX_MESSAGE],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })


def _escape(value):
    """يهرّب المحارف الخاصّة كي لا تُفسد وسوم HTML في الرسالة."""
    return html.escape(str(value), quote=False)


def format_tender(match):
    """يصوغ رسالة تنبيه واحدة تحوي العنوان والتاريخ والرابط المباشر."""
    lines = [
        "🔔 <b>مناقصة جديدة مطابقة لنشاط السفر والسياحة</b>",
        "",
        "📌 <b>الموضوع:</b> %s" % _escape(match.title),
        "🏛 <b>الجهة المُعلِنة:</b> %s" % _escape(match.entity),
        "🗓 <b>تاريخ النشر:</b> %s" % _escape(match.date),
        "⏳ <b>آخر موعد:</b> %s" % _escape(match.deadline),
    ]

    if match.number:
        lines.append("🔢 <b>رقم الإعلان:</b> %s" % _escape(match.number))
    if match.attachments:
        lines.append("📎 <b>المرفقات:</b> %d ملف" % match.attachments)

    keywords = sorted(set(match.title_hits) | set(match.body_hits))
    if keywords:
        lines.append("🎯 <b>الكلمات المُطابِقة:</b> %s" % _escape("، ".join(keywords)))

    lines += [
        "",
        '🔗 <a href="%s">فتح الإعلان على المنصة</a>' % _escape(match.url),
    ]
    return "\n".join(lines)


def format_summary(matches, total_scanned):
    """رسالة موجزة تُستخدم في التشغيل الأول لتفادي إغراق الهاتف بالأرشيف."""
    lines = [
        "✅ <b>تم تفعيل مراقبة منصة العطاءات الحكومية</b>",
        "",
        "تم فحص <b>%d</b> إعلاناً منشوراً على المنصة." % total_scanned,
        "وُجد <b>%d</b> إعلاناً مطابقاً لنشاط السفر والسياحة." % len(matches),
        "",
        "سيصلك من الآن فصاعداً تنبيه فوري بكل إعلان <b>جديد</b> فقط.",
    ]
    return "\n".join(lines)

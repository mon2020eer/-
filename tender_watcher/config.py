# -*- coding: utf-8 -*-
"""إعدادات التشغيل، تُقرأ من متغيّرات البيئة (أسرار GitHub) مع قيم افتراضية آمنة."""

import json
import os
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent

PORTAL_ORIGIN = "https://www.attaat.pm.gov.ly"
API_PATH = "/back_api/api/PublicAttaat"
TENDER_URL_TEMPLATE = PORTAL_ORIGIN + "/atta/{id}"

# الكلمات المفتاحية الافتراضية لقطاع السفر والسياحة.
# تُكتب كجذور مجرّدة من «ال» التعريف لأنّ المُطابِق يتكفّل بالسوابق واللواحق.
DEFAULT_KEYWORDS = [
    "تذاكر",      # تذاكر
    "تداكر",      # خطأ إملائي شائع رُصد فعلياً في إعلانات المنصة
    "تذكر",       # تذكرة
    "سفر",        # سفر
    "سياح",       # سياحة / سياحي / السياحية
    "فندق",       # فندق
    "فنادق",      # فنادق
    "طيران",      # طيران
    "تاشير",      # تأشيرة / تأشيرات (بعد التطبيع)
    "حجز",        # حجز
    "رحلات",      # رحلات
    "رحله",       # رحلة
    "مطار",       # مطار
    "عمره",       # عمرة
    "حجاج",       # حجاج
    "مبيت",       # مبيت / إقامة
    "نقل ركاب",   # عبارة مركّبة
]


def _env(name, default=None):
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_int(name, default):
    try:
        return int(_env(name, "") or default)
    except (TypeError, ValueError):
        return default


def load_keywords():
    """يحمّل الكلمات المفتاحية من keywords.json إن وُجد، وإلّا القائمة الافتراضية.

    يمكن كذلك تجاوزهما عبر متغيّر البيئة KEYWORDS (مفصولة بفواصل)، وهو الأنسب
    للتعديل السريع من هاتفك دون تحرير أي ملف.
    """
    override = _env("KEYWORDS")
    if override:
        words = [w.strip() for w in override.split(",") if w.strip()]
        if words:
            return words

    keywords_file = BASE_DIR / "keywords.json"
    if keywords_file.exists():
        try:
            data = json.loads(keywords_file.read_text(encoding="utf-8"))
            words = [str(w).strip() for w in data.get("keywords", []) if str(w).strip()]
            if words:
                return words
        except (ValueError, OSError):
            pass

    return list(DEFAULT_KEYWORDS)


class Settings(object):
    """يجمع كل ما يحتاجه التشغيل في كائن واحد ويتحقّق من اكتمال الأسرار."""

    def __init__(self):
        self.telegram_token = _env("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = _env("TELEGRAM_CHAT_ID")
        self.keywords = load_keywords()

        # وزن المطابقة: العنوان أقوى دلالة بكثير من نصّ الإعلان
        self.title_weight = _env_int("TITLE_WEIGHT", 3)
        self.description_weight = _env_int("DESCRIPTION_WEIGHT", 1)
        # الحد الأدنى للنتيجة كي يُرسَل التنبيه (2 يعني: مطابقة عنوان واحدة تكفي)
        self.min_score = _env_int("MIN_SCORE", 2)

        self.page_size = _env_int("PAGE_SIZE", 50)
        self.max_pages = _env_int("MAX_PAGES", 20)
        self.request_timeout = _env_int("REQUEST_TIMEOUT", 45)
        self.max_retries = _env_int("MAX_RETRIES", 4)

        # في التشغيل الأول لا نُغرق الهاتف بكل الأرشيف المطابق
        self.first_run_alert_limit = _env_int("FIRST_RUN_ALERT_LIMIT", 5)
        self.max_alerts_per_run = _env_int("MAX_ALERTS_PER_RUN", 20)
        self.state_file = BASE_DIR / _env("STATE_FILE", "state/seen.json")

    def validate(self):
        """يُرجع قائمة بالأسرار الناقصة (فارغة تعني أنّ الإعداد مكتمل)."""
        missing = []
        if not self.telegram_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return missing

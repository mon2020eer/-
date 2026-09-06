# -*- coding: utf-8 -*-
"""عميل الاتصال بمنصة العطاءات الحكومية الليبية.

ملاحظة معمارية مهمّة:
الصفحة الرئيسية للمنصة تطبيق Angular أحادي الصفحة (SPA)؛ فالمصدر الأوّلي
لا يحتوي إلّا على الوسم <app-root></app-root> دون أي بيانات مناقصات. لذلك فإنّ
تحليل صفحة HTML وحدها لا يُنتج أي نتيجة إطلاقاً، والمصدر الصحيح للبيانات هو
واجهة JSON التي يستدعيها التطبيق نفسه:

    POST /back_api/api/PublicAttaat
    {"sortBy","sortOrder","pageNumber","pageSize","biddingTypeId","governmentalEntityId"}
    ← {"count": <العدد الكلي>, "list": [ ... ]}

وهذا المسار أدقّ وأثبت من تحليل HTML لأنّه لا يتأثّر بتغيّر التنسيق.
وتُستخدم BeautifulSoup هنا في موضعين حقيقيين:
  1) قراءة صفحة SPA لاكتشاف حزمة الجافاسكربت والتحقّق من مسار الواجهة تلقائياً،
     فتظلّ الأداة عاملة إذا غيّرت المنصة بصمة الملف أو مسار الواجهة.
  2) تنظيف أي وسوم HTML قد ترد داخل حقول العنوان أو نصّ الإعلان.
"""

import re
import time

import requests
from bs4 import BeautifulSoup

from . import config

_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

_BASE_URL_PATTERN = re.compile(r"baseUrl\s*:\s*window\.location\.origin\s*\+\s*[\"']([^\"']+)[\"']")


class PortalError(RuntimeError):
    """خطأ في جلب البيانات من المنصة بعد استنفاد كل المحاولات."""


def build_session():
    """ينشئ جلسة requests بترويسات تحاكي متصفّح المنصة."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ar,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": config.PORTAL_ORIGIN,
        "Referer": config.PORTAL_ORIGIN + "/",
    })
    return session


def clean_html_text(value):
    """يُزيل أي وسوم HTML ويُوحّد المسافات، عبر BeautifulSoup."""
    if not value:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def discover_api_path(session):
    """يكتشف مسار الواجهة من حزمة الجافاسكربت، ويرجع الافتراضي عند التعذّر.

    يقرأ الصفحة الرئيسية بـ BeautifulSoup، ويستخرج وسوم <script>، ثم يبحث في
    حزمة main عن تعريف baseUrl. هذا يجعل الأداة تتكيّف تلقائياً إذا بدّلت
    المنصة مسار الواجهة الخلفية.
    """
    try:
        response = session.get(config.PORTAL_ORIGIN + "/", timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        scripts = [
            tag.get("src")
            for tag in soup.find_all("script")
            if tag.get("src") and "main" in tag.get("src")
        ]
        for src in scripts:
            bundle_url = src if src.startswith("http") else "%s/%s" % (
                config.PORTAL_ORIGIN, src.lstrip("/")
            )
            bundle = session.get(bundle_url, timeout=40)
            if not bundle.ok:
                continue
            found = _BASE_URL_PATTERN.search(bundle.text)
            if found:
                return "%s/api/PublicAttaat" % found.group(1).rstrip("/")
    except (requests.RequestException, ValueError):
        pass
    return config.API_PATH


def _post_page(session, api_path, page_number, settings):
    """يطلب صفحة واحدة من الإعلانات مع إعادة المحاولة والتراجع الأسّي."""
    payload = {
        "sortBy": "publishDate",
        "sortOrder": "desc",
        "pageNumber": page_number,
        "pageSize": settings.page_size,
        "biddingTypeId": 0,
        "governmentalEntityId": 0,
    }
    url = config.PORTAL_ORIGIN + api_path
    delay = 2
    last_error = None

    for attempt in range(1, settings.max_retries + 1):
        try:
            response = session.post(url, json=payload, timeout=settings.request_timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < settings.max_retries:
                time.sleep(delay)
                delay *= 2  # تراجع أسّي: 2 ثم 4 ثم 8 ثوانٍ

    raise PortalError("تعذّر جلب الصفحة رقم %d: %s" % (page_number, last_error))


def fetch_tenders(settings, session=None):
    """يجلب كل الإعلانات المنشورة مرتّبة من الأحدث إلى الأقدم."""
    session = session or build_session()
    api_path = discover_api_path(session)

    tenders = []
    total = None

    for page in range(settings.max_pages):
        data = _post_page(session, api_path, page, settings)
        items = data.get("list") or []
        if total is None:
            total = data.get("count", 0)
        tenders.extend(items)
        if not items or len(tenders) >= (total or 0):
            break

    return tenders

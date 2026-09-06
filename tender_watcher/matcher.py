# -*- coding: utf-8 -*-
"""ترشيح الإعلانات وتحويلها إلى نتائج مطابقة مُقيَّمة."""

import collections
import datetime

from . import config
from .arabic import find_keywords, neutralize_entity_name
from .portal import clean_html_text

MatchResult = collections.namedtuple(
    "MatchResult",
    "tender_id number title entity date deadline url score title_hits body_hits attachments",
)


def _format_date(raw):
    """يحوّل التاريخ من صيغة ISO إلى صيغة مقروءة، ويتجاهل الأخطاء بهدوء."""
    if not raw:
        return "غير محدّد"
    try:
        return datetime.datetime.fromisoformat(str(raw)[:19]).strftime("%Y-%m-%d")
    except ValueError:
        return str(raw)[:10]


def evaluate(tender, settings):
    """يُقيّم إعلاناً واحداً ويُرجع MatchResult عند تجاوزه الحدّ الأدنى، وإلّا None."""
    title = clean_html_text(tender.get("title"))
    description = clean_html_text(tender.get("description"))
    entity = (tender.get("governmentalEntity") or {}).get("name", "") or ""

    title_hits = find_keywords(title, settings.keywords)
    # يُحيَّد اسم الجهة المُعلِنة أولاً كي لا تُحتسب كلماته مطابقةً لموضوع المناقصة
    body_hits = find_keywords(
        neutralize_entity_name(description, entity), settings.keywords
    )

    score = (
        settings.title_weight * len(title_hits)
        + settings.description_weight * len(body_hits)
    )
    if score < settings.min_score:
        return None

    return MatchResult(
        tender_id=tender.get("id"),
        number=tender.get("biddingNumber"),
        title=title or "بدون عنوان",
        entity=entity or "غير محدّدة",
        date=_format_date(tender.get("publishDate")),
        deadline=_format_date(tender.get("toDate")),
        url=config.TENDER_URL_TEMPLATE.format(id=tender.get("id")),
        score=score,
        title_hits=sorted(title_hits),
        body_hits=sorted(body_hits),
        attachments=len(tender.get("biddingAttachments") or []),
    )


def filter_tenders(tenders, settings):
    """يُرجع كل الإعلانات المطابقة مرتّبة تنازلياً حسب قوة المطابقة."""
    results = []
    for tender in tenders:
        match = evaluate(tender, settings)
        if match:
            results.append(match)
    results.sort(key=lambda item: item.score, reverse=True)
    return results

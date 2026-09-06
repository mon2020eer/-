# -*- coding: utf-8 -*-
"""حفظ معرّفات الإعلانات التي سبق التنبيه عنها، لمنع تكرار الرسائل.

GitHub Actions بيئة عديمة الحالة: كل تشغيل يبدأ من نسخة نظيفة. لذلك يُحفظ
الملف داخل المستودع نفسه ويُودَع بعد كل تشغيل، وهو أبسط وأثبت خيار مجاني
(لا يعتمد على قاعدة بيانات ولا على ذاكرة مؤقّتة قابلة للإخلاء).
"""

import json
import os

# سقف لعدد المعرّفات المحفوظة كي لا ينمو الملف بلا حدّ
_MAX_TRACKED_IDS = 3000


class SeenStore(object):
    """مخزن المعرّفات المُنبَّه عنها سابقاً."""

    def __init__(self, path):
        self.path = path
        self.ids = []
        self.is_first_run = True
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.ids = [str(i) for i in data.get("seen_ids", [])]
            self.is_first_run = False
        except (ValueError, OSError):
            # ملف تالف: يُعامَل كتشغيل أول بدلاً من إيقاف الأداة
            self.ids = []
            self.is_first_run = True

    def __contains__(self, tender_id):
        return str(tender_id) in set(self.ids)

    def add_many(self, tender_ids):
        known = set(self.ids)
        for tender_id in tender_ids:
            tender_id = str(tender_id)
            if tender_id not in known:
                known.add(tender_id)
                self.ids.append(tender_id)
        # نحتفظ بالأحدث فقط عند تجاوز السقف
        if len(self.ids) > _MAX_TRACKED_IDS:
            self.ids = self.ids[-_MAX_TRACKED_IDS:]

    def save(self, last_run_iso, total_scanned):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "last_run": last_run_iso,
            "total_scanned": total_scanned,
            "seen_ids": self.ids,
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

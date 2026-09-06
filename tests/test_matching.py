# -*- coding: utf-8 -*-
"""اختبارات تُثبّت سلوك المطابقة العربية وتمنع عودة الأخطاء المرصودة فعلياً.

كل الحالات أدناه مأخوذة من إعلانات حقيقية على منصة العطاءات الحكومية.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tender_watcher.arabic import find_keywords, neutralize_entity_name, normalize
from tender_watcher.config import DEFAULT_KEYWORDS, Settings
from tender_watcher.matcher import evaluate


class NormalizationTests(unittest.TestCase):
    def test_alef_forms_unified(self):
        self.assertEqual(normalize("تأشيرات"), normalize("تاشيرات"))

    def test_taa_marbuta_and_alef_maqsura(self):
        self.assertEqual(normalize("سياحة"), "سياحه")
        self.assertEqual(normalize("الي"), normalize("إلى"))

    def test_diacritics_and_tatweel_removed(self):
        self.assertEqual(normalize("سَفَــر"), "سفر")


class KeywordMatchingTests(unittest.TestCase):
    def test_matches_definite_article_and_prefixes(self):
        for text in ["السفر", "للسفر", "والسفر", "بالسفر"]:
            self.assertIn("سفر", find_keywords(text, ["سفر"]), text)

    def test_rejects_safarja_false_positive(self):
        """«السفرجة» خدمات ضيافة ونظافة، وليست سفراً — يجب ألّا تُطابق."""
        for text in ["السفرجة والنظافة", "خدمات السفرجة والضيافة", "شركة سفرجة"]:
            self.assertEqual(set(), find_keywords(text, ["سفر"]), text)

    def test_matches_real_travel_titles(self):
        self.assertTrue(find_keywords("شركات سفر وسياحة", DEFAULT_KEYWORDS))
        self.assertTrue(find_keywords("مطلوب تداكر سفر الي ( الفلبين)", DEFAULT_KEYWORDS))

    def test_multiword_phrase(self):
        self.assertIn(normalize("نقل ركاب"), find_keywords("عقد نقل ركاب", ["نقل ركاب"]))


class EntityNeutralizationTests(unittest.TestCase):
    def test_removes_issuing_authority_name(self):
        """اسم الجهة المُعلِنة يجب ألّا يُحتسب موضوعاً للمناقصة."""
        description = "يعلن الجهاز التنفيذي للطيران الخاص عن رغبته في توريد خزانات وقود"
        cleaned = neutralize_entity_name(description, "الجهاز التنفيذي للطيران الخاص")
        self.assertEqual(set(), find_keywords(cleaned, ["طيران"]))

    def test_handles_dash_separated_entity(self):
        description = "تعلن وزارة السياحة والصناعات التقليدية عن حاجتها لتوريد معدات"
        entity = "ديوان الوزارة - وزارة السياحة والصناعات التقليدية"
        cleaned = neutralize_entity_name(description, entity)
        self.assertEqual(set(), find_keywords(cleaned, ["سياح"]))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.settings.keywords = DEFAULT_KEYWORDS

    def _tender(self, title, description="", entity=""):
        return {
            "id": "test-id", "biddingNumber": 1, "title": title,
            "description": description, "publishDate": "2026-09-05T10:00:00",
            "toDate": "2026-09-11T10:00:00",
            "governmentalEntity": {"name": entity}, "biddingAttachments": [],
        }

    def test_title_match_alerts(self):
        self.assertIsNotNone(evaluate(self._tender("خدمات سفر وسياحة"), self.settings))

    def test_catering_tender_is_ignored(self):
        tender = self._tender(
            "التعاقد مع شركة متخصصة في مجال السفرجة والنظافة",
            "يعلن المعهد عن رغبته في التعاقد في مجالي النظافة والسفرجة",
            "المعهد الليبي للمالية العامة",
        )
        self.assertIsNone(evaluate(tender, self.settings))

    def test_aviation_authority_fuel_tanks_ignored(self):
        tender = self._tender(
            "توريد وتركيب خزانات وقود",
            "يعلن الجهاز التنفيذي للطيران الخاص للشركات المتخصصة في مجال توريد وتركيب",
            "الجهاز التنفيذي للطيران الخاص",
        )
        self.assertIsNone(evaluate(tender, self.settings))

    def test_result_contains_direct_link(self):
        match = evaluate(self._tender("شركات سفر وسياحة"), self.settings)
        self.assertTrue(match.url.startswith("https://www.attaat.pm.gov.ly/atta/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""معالجة النصوص العربية ومطابقة الكلمات المفتاحية.

سبب وجود هذه الوحدة: المطابقة الحرفية المباشرة (substring) تنتج نتائج خاطئة
كثيرة في اللغة العربية. المثال الواقعي المُلاحَظ على المنصة أن كلمة «السفرجة»
(خدمات الضيافة) تحتوي حرفياً على جذر «سفر»، فتُصنَّف مناقصة نظافة وضيافة
على أنها مناقصة سفر. لذلك تعتمد هذه الوحدة على:

  1) التطبيع (normalization): توحيد صور الألف والياء والتاء المربوطة وحذف
     التشكيل والتطويل، حتى تتطابق «تأشيرات» و«تاشيرات».
  2) المطابقة الصرفية: تقسيم النص إلى كلمات، ثم قبول الكلمة فقط إذا كانت
     مساوية للجذر أو الجذر مع سابقة/لاحقة عربية معروفة. وبذلك تُقبل «للسفر»
     و«والسياحة» وتُرفض «السفرجة».
"""

import re
import unicodedata

# التشكيل وعلامات الضبط وحرف التطويل
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

# نطاق الحروف العربية لاستخراج الكلمات
_ARABIC_WORD = re.compile(r"[؀-ۿ]+")

# السوابق العربية الشائعة (أدوات التعريف وحروف الجر والعطف)
_PREFIXES = (
    "", "ال", "و", "ف", "ب", "ك", "ل", "لل",
    "بال", "وال", "فال", "كال", "ولل", "بالل", "فبال",
)

# اللواحق العربية الشائعة (التأنيث والجمع والنسب والضمائر)
_SUFFIXES = (
    "", "ه", "ات", "ية", "يه", "ين", "ون", "ي", "ا", "ها", "هم", "يات",
)

# الحد الأدنى لطول جزء اسم الجهة الذي يُحيَّد قبل المطابقة
_MIN_ENTITY_SEGMENT = 8


def normalize(text):
    """يُرجع صورة مُوحَّدة من النص العربي صالحة للمقارنة.

    يوحّد: أ إ آ ٱ ← ا، ى ← ي، ؤ ئ ← و ي، ة ← ه، ويحذف التشكيل والتطويل
    ويضغط المسافات المتكرّرة.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[أإآٱ]", "ا", text)
    text = (
        text.replace("ى", "ي")   # ى ← ي
        .replace("ؤ", "و")       # ؤ ← و
        .replace("ئ", "ي")       # ئ ← ي
        .replace("ة", "ه")       # ة ← ه
    )
    return re.sub(r"\s+", " ", text).strip()


def _strip_affixes(word, stems):
    """يفحص كلمة واحدة ويُرجع الجذر المطابق لها بعد إزالة السوابق واللواحق."""
    for prefix in _PREFIXES:
        if not word.startswith(prefix):
            continue
        remainder = word[len(prefix):]
        for suffix in _SUFFIXES:
            if suffix and not remainder.endswith(suffix):
                continue
            core = remainder[: len(remainder) - len(suffix)] if suffix else remainder
            if core in stems:
                return core
    return None


def find_keywords(text, keywords):
    """يُرجع مجموعة الجذور المطابقة داخل النص.

    الجذور المفردة تُطابَق صرفياً على مستوى الكلمة، أمّا العبارات المركّبة
    (التي تحتوي مسافة مثل «نقل ركاب») فتُطابَق كعبارة داخل النص المُطبَّع.
    """
    normalized_text = normalize(text)
    single_stems = {normalize(k) for k in keywords if " " not in k.strip()}
    phrases = {normalize(k) for k in keywords if " " in k.strip()}

    matches = set()
    for word in _ARABIC_WORD.findall(normalized_text):
        stem = _strip_affixes(word, single_stems)
        if stem:
            matches.add(stem)

    for phrase in phrases:
        if phrase and phrase in normalized_text:
            matches.add(phrase)

    return matches


def neutralize_entity_name(description, entity_name):
    """يحذف اسم الجهة المُعلِنة من نصّ الإعلان قبل المطابقة.

    المبرّر: كثير من الإعلانات تبدأ بعبارة «تعلن وزارة السياحة…» أو «يعلن
    الجهاز التنفيذي للطيران…»، فيلتقط المُطابِق كلمة «سياحة» أو «طيران» من
    اسم الجهة لا من موضوع المناقصة. وقد رُصدت هذه الحالة فعلياً في إعلان
    «توريد وتركيب خزانات وقود» الصادر عن جهاز الطيران، وهو إعلان لا يمتّ
    لنشاط السفر بصلة.
    """
    cleaned = normalize(description)
    for segment in re.split(r"[-–—/|]", entity_name or ""):
        segment = normalize(segment)
        if len(segment) >= _MIN_ENTITY_SEGMENT:
            cleaned = cleaned.replace(segment, " ")
    return cleaned

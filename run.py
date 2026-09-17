# -*- coding: utf-8 -*-
"""نقطة تشغيل منظومة إدارة مكتب إيجار السيارات — للحزم التنفيذية.

**لماذا ملف منفصل عن `app/__main__.py`؟** لأن PyInstaller تشغّل ملفَ نقطة
الدخول باسم `__main__` **بلا سياق حزمة** (`__package__ = None`)، فتسقط كل
استيراداته النسبية:

    ImportError: attempted relative import with no known parent package

و`app/__main__.py` مليء بها (`from . import config` …) وهي صحيحة تماماً عند
`python -m app` لأن المفسّر يمنحها السياق حينها. فالحلّ ألّا يكون هو نقطة
الدخول، بل هذا الملف: يستورد الحزمة **استيراداً مطلقاً** فيصير لها سياقها.

    python -m app      ← الطريق المعتاد للمطوّر (لم يتغيّر)
    python run.py      ← الطريق الذي تسلكه النسخة المحزومة
"""

import os
import sys


def _ensure_importable():
    """يضمن أن مجلد المشروع في مسار البحث عند التشغيل المباشر."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


_ensure_importable()

from app.__main__ import main  # noqa: E402  (بعد ضبط المسار عمداً)

if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""تهيئة الواجهة العربية من اليمين إلى اليسار.

اتجاه الواجهة يُضبط **مرّة واحدة على مستوى التطبيق كلّه** لا على كل نافذة:
عندها تنعكس تلقائياً محاذاة النصوص، وترتيب أزرار الحوارات، وموضع رؤوس
الجداول وأسهم القوائم المنسدلة، وحتى اتجاه شريط التمرير.
"""

import pathlib

from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from .. import config

_THEME_FILE = pathlib.Path(__file__).with_name("theme.qss")

# سلسلة الخطوط: خطوط ويندوز الأصلية أولاً لأنّها تعرض العربية عرضاً ممتازاً
# ولا تحتاج تضمين ملفات خطوط في البرنامج. البقيّة بدائل للينكس والتطوير.
FONT_CANDIDATES = (
    "Segoe UI",
    "Tahoma",
    "Dubai",
    "Cairo",
    "Noto Naskh Arabic",
    "Noto Sans Arabic",
    "DejaVu Sans",
)


def pick_font(size=11):
    """يختار أول خط متوفّر من السلسلة، ويرجع إلى خط النظام إن لم يتوفّر شيء."""
    families = set(QFontDatabase.families())
    for name in FONT_CANDIDATES:
        if name in families:
            return QFont(name, size)
    return QFont(QApplication.font().family(), size)


def load_stylesheet():
    """يقرأ ملف نمط الواجهة."""
    if _THEME_FILE.is_file():
        return _THEME_FILE.read_text(encoding="utf-8")
    return ""


def apply(app):
    """يطبّق الاتجاه واللغة والخط والنمط على التطبيق. يُستدعى مرّة عند الإقلاع."""
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_TITLE_AR)
    app.setApplicationVersion(config.APP_VERSION)

    # لغة الواجهة عربية بتقويم ميلادي وأرقام لاتينية،
    # فالأرقام اللاتينية أوضح في الجداول المالية وفي حقول الإدخال.
    locale = QLocale(QLocale.Language.Arabic, QLocale.Country.Libya)
    locale.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    QLocale.setDefault(locale)

    app.setFont(pick_font())
    app.setStyleSheet(load_stylesheet())
    return app

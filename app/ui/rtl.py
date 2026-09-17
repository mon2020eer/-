# -*- coding: utf-8 -*-
"""تهيئة الواجهة العربية من اليمين إلى اليسار.

اتجاه الواجهة يُضبط **مرّة واحدة على مستوى التطبيق كلّه** لا على كل نافذة:
عندها تنعكس تلقائياً محاذاة النصوص، وترتيب أزرار الحوارات، وموضع رؤوس
الجداول وأسهم القوائم المنسدلة، وحتى اتجاه شريط التمرير.
"""

import pathlib

from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
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


# لوحة ألوان التطبيق — فاتحة صريحة لا موروثة من النظام.
#
# **لماذا تُثبَّت بدل أن تُترك للنظام؟** ورقة الأنماط تلوّن حقول الإدخال بتعداد
# أسماء أصنافها (`QLineEdit, QComboBox, …`). وكل صنف لا يرد في ذلك التعداد يسقط
# إلى لوحة ألوان نظام التشغيل: ويندوز ١١ في الوضع الداكن يعطيه خلفية سوداء،
# ويبقى نصّه داكناً — فيصير داكناً على داكن لا يُقرأ.
#
# ووقع ذلك فعلاً على جهاز المالك: حقل الوقت في حوار العقد الجديد، وجسم القائمة
# المنسدلة في حوار المستخدم الجديد. وعلاجُه بإضافة الأسماء الناقصة علاجٌ لليوم
# وحده: كل صنف يُضاف غداً يولد أسود من جديد، ولا يُكتشف إلّا على جهاز عميل.
#
# فالمنظومة مصمَّمة فاتحة — كل ألوان `theme.qss` فاتحة — ومن حقّها أن تقول ذلك
# صراحةً مرّة واحدة، بدل أن تفاوض نظام التشغيل عنصراً عنصراً.
LIGHT_PALETTE_COLORS = {
    QPalette.ColorRole.Window:          "#f4f6f9",   # خلفية النوافذ
    QPalette.ColorRole.WindowText:      "#1f2937",   # نصّ عام
    QPalette.ColorRole.Base:            "#ffffff",   # خلفية حقول الإدخال
    QPalette.ColorRole.AlternateBase:   "#f1f3f6",   # صفوف الجداول المتناوبة
    QPalette.ColorRole.Text:            "#1f2937",   # نصّ الحقول
    QPalette.ColorRole.Button:          "#ffffff",
    QPalette.ColorRole.ButtonText:      "#1f2937",
    QPalette.ColorRole.ToolTipBase:     "#ffffff",
    QPalette.ColorRole.ToolTipText:     "#1f2937",
    QPalette.ColorRole.PlaceholderText: "#9aa4b2",
    QPalette.ColorRole.Highlight:       "#2f6fed",   # التحديد
    QPalette.ColorRole.HighlightedText: "#ffffff",
}


def light_palette():
    """لوحة ألوان فاتحة صريحة، مستقلّة عن وضع نظام التشغيل."""
    palette = QPalette()
    for role, value in LIGHT_PALETTE_COLORS.items():
        palette.setColor(role, QColor(value))
    return palette


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
    # قبل ورقة الأنماط: الأنماط تبني فوق اللوحة لا العكس
    app.setPalette(light_palette())
    app.setStyleSheet(load_stylesheet())
    return app

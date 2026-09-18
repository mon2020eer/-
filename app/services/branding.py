# -*- coding: utf-8 -*-
"""هوية الشركة: الاسم والهواتف والعنوان والسجلّ التجاري والشعار.

**لماذا وحدة مستقلّة؟** لأن الهوية كانت تُقرأ في ثلاثة مواضع على الأقلّ — ترويسة
العقد المولَّد، وملء نموذج المكتب، والتقارير — وكلٌّ يقرأ ما يحتاجه بطريقته
ويكتب اسمه الافتراضي عند الغياب. فاسمٌ يُغيَّر في الإعدادات كان يظهر في ورقة
ويغيب عن أخرى.

وهذه الوحدة هي **المصدر الوحيد**: من أراد اسم الشركة أخذه من هنا، فإن غيّره
صاحبها من الإعدادات تغيّر في كل ورقة تخرج من المنظومة.

الشعار **يُنسخ** إلى مجلد البيانات عند رفعه — كنموذج العقد تماماً: الملف الأصلي
قد يُحذف أو يكون على فلاشة، وترويسةٌ بلا شعار لأن مالكه نقل ملفاً عطبٌ يوم العمل.
"""

import base64
import pathlib

from .. import config
from ..repositories import settings_repo

# مفاتيح الهوية في ``app_settings``. أوّلان منها قديمان يعملان منذ الإصدار
# الأول، فلا تُغيَّر أسماؤهما وإلّا فقد كل مكتب قائم بياناته المحفوظة.
KEY_NAME = "office_name"
KEY_PHONE = "office_phone"
KEY_ADDRESS = "office_address"
KEY_PHONE_ALT = "office_phone_alt"
KEY_REGISTER = "commercial_register"
KEY_LOGO = "office_logo"

LOGO_DIR_NAME = "branding"
LOGO_FILE_NAME = "logo.png"

# صيغ الصور التي يقبلها Qt بلا إضافات، بامتدادها كما يكتبها المستخدم
LOGO_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

# حدّ حجم الشعار. صورةٌ بحجم ميغابايتات تُدرج في كل PDF فتضخّم كل عقد بلا فائدة
# تُرى على ورقة A4.
MAX_LOGO_BYTES = 4 * 1024 * 1024


class BrandingError(Exception):
    """خطأ في بيانات الهوية أو في ملف الشعار، برسالة عربية تصلح للعرض."""


def identity(conn=None):
    """بيانات الشركة كما ضبطها صاحبها — قاموسٌ قيمُه نصوص دائماً.

    الاسم وحده له بديل عند الغياب (عنوان التطبيق)، لأن ورقةً بلا اسم في
    ترويستها ليست عقداً. وما عداه يبقى فارغاً: عنوانٌ مُختلَق أسوأ من لا عنوان.
    """
    values = settings_repo.all_settings(conn=conn)

    def value(key):
        return (values.get(key) or "").strip()

    return {
        "name": value(KEY_NAME) or config.APP_TITLE_AR,
        "phone": value(KEY_PHONE),
        "phone_alt": value(KEY_PHONE_ALT),
        "address": value(KEY_ADDRESS),
        "commercial_register": value(KEY_REGISTER),
    }


def contact_line(conn=None):
    """سطر التواصل تحت اسم الشركة في الترويسة، بلا فواصل معلَّقة.

    الأجزاء الفارغة تُسقَط لا تُطبع شرطةً بلا ما بعدها: مكتبٌ لم يُدخل سجلّه
    التجاري بعدُ لا يستحقّ ترويسة تنتهي بـ «— س.ت:».
    """
    data = identity(conn=conn)
    phones = " / ".join(part for part in (data["phone"], data["phone_alt"]) if part)

    parts = [data["address"], phones]
    if data["commercial_register"]:
        parts.append("س.ت: %s" % data["commercial_register"])

    return " — ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# الشعار
# ---------------------------------------------------------------------------
def logo_path():
    """مسار الشعار المحفوظ إن وُجد فعلاً على القرص، وإلّا ``None``.

    يُتحقَّق من الملف لا من الإعداد وحده: مكتبٌ حذف الصورة من مجلد البيانات
    يدوياً كان يجعل الطباعة تحاول قراءة ملف غير موجود عند كل عقد.
    """
    path = pathlib.Path(config.DATA_DIR) / LOGO_DIR_NAME / LOGO_FILE_NAME
    return path if path.is_file() else None


def has_logo():
    return logo_path() is not None


def install_logo(source_path):
    """ينسخ ملف الشعار إلى مجلد البيانات ويُرجع مساره."""
    source = pathlib.Path(source_path)
    if not source.is_file():
        raise BrandingError("الملف غير موجود: %s" % source)
    if source.suffix.lower() not in LOGO_SUFFIXES:
        raise BrandingError(
            "صيغة غير مدعومة. اختر صورة بإحدى الصيغ: %s"
            % "، ".join(suffix.lstrip(".").upper() for suffix in LOGO_SUFFIXES)
        )
    if source.stat().st_size > MAX_LOGO_BYTES:
        raise BrandingError(
            "حجم الصورة يتجاوز %d ميغابايت. اختر صورة أصغر — الشعار يُدرج في كل"
            " عقد يُطبع." % (MAX_LOGO_BYTES // (1024 * 1024))
        )

    destination = pathlib.Path(config.DATA_DIR) / LOGO_DIR_NAME / LOGO_FILE_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)

    # يُحوَّل إلى PNG دائماً مهما كانت صيغة المصدر، فيبقى اسم ملف واحد ولا
    # تتراكم صور بامتدادات مختلفة يظنّ كلٌّ منها أنه الشعار.
    from PyQt6.QtGui import QImage

    image = QImage(str(source))
    if image.isNull():
        raise BrandingError("تعذّرت قراءة الصورة. تأكّد أنها ملف صورة سليم.")
    if not image.save(str(destination), "PNG"):
        raise BrandingError("تعذّر حفظ الشعار في مجلد بيانات التطبيق.")

    settings_repo.set_value(KEY_LOGO, LOGO_FILE_NAME)
    return destination


def remove_logo():
    """يحذف الشعار وإعداده معاً — فلا يبقى إعداد يشير إلى ملف ذهب."""
    path = pathlib.Path(config.DATA_DIR) / LOGO_DIR_NAME / LOGO_FILE_NAME
    if path.exists():
        path.unlink()
    settings_repo.set_value(KEY_LOGO, "")


def logo_data_uri():
    """الشعار بترميز ``data:`` جاهزاً لوسم ``<img>`` في HTML الطباعة.

    يُدرج مضمَّناً لا بمسار ملف: ``QTextDocument`` تُطبع في سياق قد لا يكون مجلد
    العمل فيه مجلد البيانات، ومسارٌ نسبي يخرج صورةً مكسورة على ورقة العقد.

    يُرجع ``None`` حين لا شعار — فتُطبع الترويسة بالاسم وحده.
    """
    path = logo_path()
    if path is None:
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/png;base64,%s" % encoded

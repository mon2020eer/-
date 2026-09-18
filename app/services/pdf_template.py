# -*- coding: utf-8 -*-
"""الطباعة على نموذج عقد المكتب.

المكتب يملك ورقة عقده المطبوعة وشروطها على ظهرها، ولا يريد ورقة أخرى من عندنا.
فيرفع ملفّه PDF مرّة واحدة، ويعيّن مواضع الحقول عليه بالفأرة، ثم تطبع المنظومة
بياناتها في مواضعها على ورقته هو.

**لماذا بلا مكتبة خارجية؟** ``PyQt6.QtPdf`` تأتي داخل حزمة PyQt6 المثبَّتة أصلاً،
فتقرأ النموذج وتصيّره صورةً، و``QPdfWriter`` يكتب الناتج. فلا تنزيل إضافي على
اتصال بطيء، ولا تبعية جديدة تُفشل حزم ويندوز، ولا مكتبة عربية هشّة: Qt تُشكّل
العربية وتصلها أصلاً — وهو سبب اختيارها لتوليد العقد منذ الإصدار الأول.

**لماذا التعيين يدوي لا تلقائي؟** استنتاج مواضع الحقول من نصّ الملف يفشل مع
النماذج الممسوحة ضوئياً (وأكثر نماذج المكاتب ممسوحة)، ويُخطئ صامتاً في غيرها —
ورقم جواز في خانة رقم اللوحة خطأ لا يُكتشف إلّا بعد الطباعة. والتعيين اليدوي
مرّة واحدة لكل مكتب أضمن، ويعطي المكتب ضبطاً كاملاً على ورقته.
"""

import json
import pathlib
import shutil

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter
from PyQt6.QtPdf import QPdfDocument

from .. import config
from ..core import features
from ..repositories import settings_repo

SETTING_KEY = "contract_template"
TEMPLATE_FILE_NAME = "office_contract.pdf"

# دقّة تصيير صفحة النموذج خلفيةً. ٢٠٠ نقطة/بوصة تكفي لورقة عقد تُقرأ وتُوقَّع،
# و٣٠٠ تضاعف حجم الملف بلا فرق يُرى على طابعة مكتب.
RENDER_DPI = 200

# دقّة كتابة الناتج. أعلى من دقّة التصيير عمداً: الخلفية صورة، أمّا النصّ الذي
# نكتبه نحن فيُرسم متّجهاً عند هذه الدقّة فيخرج حادّاً مهما كبر التكبير.
OUTPUT_DPI = 300

POINTS_PER_INCH = 72.0

DEFAULT_FONT_SIZE = 11
DEFAULT_ALIGN = "right"

_ALIGN_FLAGS = {
    "right": Qt.AlignmentFlag.AlignRight,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "left": Qt.AlignmentFlag.AlignLeft,
}

ALIGN_LABELS = {
    "right": "لليمين",
    "center": "توسيط",
    "left": "لليسار",
}


class TemplateError(Exception):
    """خطأ في النموذج أو في تعيينه، برسالة عربية تصلح للعرض."""


# ---------------------------------------------------------------------------
# الحقول المتاحة للتعيين
# ---------------------------------------------------------------------------
# (المفتاح، التسمية العربية، المجموعة). التسمية هي ما يراه المكتب في المحرّر،
# والمفتاح هو ما يُخزَّن — فتغيير التسمية لا يُبطل تعييناً محفوظاً.
FIELDS = (
    ("customer_name",        "الاسم بالكامل",        "المستأجر"),
    ("customer_nationality", "الجنسية",               "المستأجر"),
    ("customer_national_id", "رقم جواز السفر",        "المستأجر"),
    ("customer_license",     "رقم رخصة القيادة",      "المستأجر"),
    ("customer_license_expiry", "صلاحية الرخصة",      "المستأجر"),
    ("customer_license_issuer", "صادرة عن",           "المستأجر"),
    ("customer_dob",         "تاريخ الميلاد",         "المستأجر"),
    ("customer_address",     "عنوان السكن",           "المستأجر"),
    ("customer_phone",       "الهاتف",                "المستأجر"),
    ("customer_work_address", "عنوان العمل",          "المستأجر"),
    ("customer_phone_alt",   "هاتف العمل / هاتف آخر", "المستأجر"),

    ("vehicle_type",         "نوع السيارة",           "السيارة"),
    ("vehicle_plate",        "رقم اللوحة",            "السيارة"),
    ("vehicle_chassis",      "رقم الهيكل",            "السيارة"),
    ("vehicle_year",         "سنة الصنع",             "السيارة"),
    ("vehicle_color",        "اللون",                 "السيارة"),
    ("vehicle_body_style",   "التصميم",               "السيارة"),
    ("vehicle_odometer",     "قراءة العدّاد",          "السيارة"),

    ("contract_number",      "رقم العقد",             "العقد"),
    ("start_date",           "تاريخ المغادرة",        "العقد"),
    ("end_date",             "تاريخ العودة",          "العقد"),
    # التسمية محايدة لأن القيمة تتبع نمط الاحتساب: أيامٌ في العقد اليومي
    # وساعاتٌ في المُغلَق بالاحتساب الساعي. والمفتاح ثابت فلا تنكسر تعيينات
    # المكاتب القائمة.
    ("days_count",           "المدّة",                 "العقد"),
    # التسمية صُحّحت: هذا الحقل هو **مكان الاستلام** الذي يُكتب في حوار العقد،
    # وكان معنوناً «مكان التجوّل» خطأً. ومكان التجوّل صار حقلاً مستقلاً أدناه،
    # فمن عيّن القديم على خانة التجوّل في ورقته فليُعِد تعيينها.
    ("pickup_location",      "مكان الاستلام",         "العقد"),
    ("allowed_area",         "مكان التجوّل",           "العقد"),
    ("guarantees",           "الضمانات المحجوزة",     "العقد"),
    ("departure_condition",  "حالة السيارة عند المغادرة", "العقد"),
    ("renewed_until",        "تم تجديد العقد إلى يوم", "العقد"),
    ("today",                "تاريخ اليوم",           "العقد"),

    ("total_amount",         "إجمالي المبلغ",         "المبالغ"),
    ("paid_amount",          "المبلغ المدفوع",        "المبالغ"),
    ("balance_amount",       "باقي المبلغ",           "المبالغ"),
    ("daily_rate",           "التعرفة",               "المبالغ"),

    ("guarantor_name",       "اسم الكفيل",            "الكفيل"),
    ("guarantor_nationality", "جنسية الكفيل",         "الكفيل"),
    ("guarantor_passport",   "رقم جواز الكفيل",       "الكفيل"),
    ("guarantor_address",    "عنوان الكفيل",          "الكفيل"),
    ("guarantor_phone",      "هاتف الكفيل",           "الكفيل"),
    ("guarantor_work_address", "عنوان عمل الكفيل",    "الكفيل"),

    ("office_name",          "اسم الشركة",            "المكتب"),
    ("office_phone",         "هاتف الشركة",           "المكتب"),
    ("office_phone_alt",     "هاتف آخر",              "المكتب"),
    ("office_address",       "عنوان الشركة",          "المكتب"),
    ("office_register",      "السجلّ التجاري",         "المكتب"),
)

FIELD_LABELS = {key: label for key, label, _ in FIELDS}
FIELD_GROUPS = tuple(dict.fromkeys(group for _, _, group in FIELDS))


def fields_of_group(group):
    return [(key, label) for key, label, name in FIELDS if name == group]


# ---------------------------------------------------------------------------
# مسار النموذج وتعيينه
# ---------------------------------------------------------------------------
def template_path():
    return pathlib.Path(config.TEMPLATES_DIR) / TEMPLATE_FILE_NAME


def has_template():
    return template_path().is_file()


def install(source_path):
    """ينسخ نموذج المكتب إلى مجلد البيانات ويُرجع مساره.

    يُنسخ ولا يُشار إليه في مكانه: الملف الأصلي قد يُحذف أو يُنقل أو يكون على
    فلاشة، وعقد لا يُطبع لأن مالكه نقل ملفاً عطبٌ يوم العمل.
    """
    features.require("contract_template")

    source = pathlib.Path(source_path)
    if not source.is_file():
        raise TemplateError("الملف غير موجود: %s" % source)

    document = QPdfDocument(None)
    if document.load(str(source)) != QPdfDocument.Error.None_:
        raise TemplateError("تعذّرت قراءة الملف. تأكّد أنه ملف PDF سليم.")
    if document.pageCount() < 1:
        raise TemplateError("الملف لا يحتوي صفحات.")

    destination = template_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def remove():
    """يحذف النموذج وتعيينه معاً — فلا يبقى تعيين بلا ورقة."""
    features.require("contract_template")
    path = template_path()
    if path.exists():
        path.unlink()
    settings_repo.set_value(SETTING_KEY, "")


def load_mapping(conn=None):
    """تعيين المواضع المحفوظ: ``{مفتاح الحقل: {page, x, y, size, align}}``."""
    raw = settings_repo.get(SETTING_KEY, "", conn=conn)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_mapping(mapping, conn=None):
    features.require("contract_template")
    settings_repo.set_value(
        SETTING_KEY, json.dumps(mapping, ensure_ascii=False), conn=conn
    )


def is_ready(conn=None):
    """جاهزٌ للطباعة: ورقة مرفوعة **مقروءة** وحقل واحد على الأقل معيَّن عليها.

    تُفتح الورقة فعلاً لا يُكتفى بوجود ملفّها: نموذجٌ رُفع ثم تلف — قرصٌ أصابه
    عطب، أو ملفّ استُبدل يدوياً — كان يجعل الطباعة تتوقّف بخطأ، فيقف المكتب
    أمام زبونه بلا عقد. وغيابُ النموذج يرجع لعقد المنظومة بهدوء، فالتلف أولى
    بأن يفعل مثله.
    """
    if not has_template() or not load_mapping(conn=conn):
        return False
    try:
        _open_document()
    except TemplateError:
        return False
    return True


# ---------------------------------------------------------------------------
# التصيير والتعبئة
# ---------------------------------------------------------------------------
def _open_document(path=None):
    document = QPdfDocument(None)
    source = pathlib.Path(path or template_path())
    if not source.is_file():
        raise TemplateError("لم يُرفع نموذج عقد للمكتب بعد.")
    if document.load(str(source)) != QPdfDocument.Error.None_:
        raise TemplateError("نموذج العقد تالف أو غير مقروء. أعد رفعه.")
    return document


def page_count(path=None):
    return _open_document(path).pageCount()


def render_page(page, dpi=RENDER_DPI, path=None):
    """يصيّر صفحة من النموذج صورةً — للمحرّر وللخلفية عند الطباعة."""
    document = _open_document(path)
    if not 0 <= page < document.pageCount():
        raise TemplateError("رقم الصفحة خارج حدود النموذج.")

    size_points = document.pagePointSize(page)
    scale = dpi / POINTS_PER_INCH
    image = document.render(
        page,
        QSize(max(1, round(size_points.width() * scale)),
              max(1, round(size_points.height() * scale))),
    )
    if image.isNull():
        raise TemplateError("تعذّر تصيير صفحة النموذج.")
    return image


def page_size_points(page, path=None):
    return _open_document(path).pagePointSize(page)


def fill(values, output_path, mapping=None, path=None, conn=None):
    """يطبع ``values`` على النموذج ويحفظ الناتج في ``output_path``.

    كل صفحة تُصيَّر خلفيةً ثم تُرسم عليها قيم حقولها؛ والصفحات التي لا حقول لها
    (صفحة الشروط مثلاً) تُنسخ كما هي فتخرج الورقة كاملة كما يعرفها المكتب.
    """
    features.require("contract_template")

    mapping = load_mapping(conn=conn) if mapping is None else mapping
    if not mapping:
        raise TemplateError(
            "لم تُحدَّد مواضع الحقول على النموذج بعد."
            " افتح الإعدادات ← نموذج عقد المكتب ← تحديد مواضع الحقول."
        )

    document = _open_document(path)
    output = pathlib.Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    writer = QPdfWriter(str(output))
    writer.setResolution(OUTPUT_DPI)
    writer.setCreator("منظومة إدارة مكتب إيجار السيارات")

    painter = QPainter()
    try:
        for page in range(document.pageCount()):
            size_points = document.pagePointSize(page)
            writer.setPageLayout(QPageLayout(
                QPageSize(size_points, QPageSize.Unit.Point),
                QPageLayout.Orientation.Portrait,
                # بلا هوامش: النموذج نفسه يحمل هوامشه المطبوعة
                writer.pageLayout().margins(),
            ))
            writer.setPageMargins(writer.pageLayout().margins())

            if page == 0:
                if not painter.begin(writer):
                    raise TemplateError("تعذّر إنشاء ملف الإخراج.")
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            else:
                writer.newPage()

            background = render_page(page, dpi=RENDER_DPI, path=path)
            target = painter.viewport()
            painter.drawImage(target, background)

            _draw_page_fields(painter, target, page, mapping, values)
    finally:
        if painter.isActive():
            painter.end()

    return output


def _draw_page_fields(painter, target, page, mapping, values):
    """يرسم قيم حقول صفحة واحدة في مواضعها النسبية."""
    painter.save()
    painter.setPen(QColor("#111111"))

    for key, spot in mapping.items():
        if int(spot.get("page", 0)) != page:
            continue

        text = values.get(key)
        if text in (None, ""):
            continue

        # الإحداثيات نسبية (0..1) لا بالبكسل: النموذج يُصيَّر بدقّات مختلفة بين
        # المحرّر والطباعة، والنسبة وحدها تصمد لذلك.
        x = float(spot.get("x", 0.5)) * target.width()
        y = float(spot.get("y", 0.5)) * target.height()

        size = int(spot.get("size", DEFAULT_FONT_SIZE) or DEFAULT_FONT_SIZE)
        font = painter.font()
        font.setPointSize(size)
        font.setFamily("Segoe UI")
        painter.setFont(font)

        metrics = painter.fontMetrics()
        height = metrics.height() * 1.4
        align = _ALIGN_FLAGS.get(spot.get("align", DEFAULT_ALIGN),
                                 Qt.AlignmentFlag.AlignRight)

        # صندوق يمتدّ من الموضع إلى حافّة الصفحة في جهة المحاذاة، فيتّسع النصّ
        # الطويل بدل أن يُقصّ عند نقطة النقر.
        if align == Qt.AlignmentFlag.AlignRight:
            box = QRectF(0, y - height / 2, x, height)
        elif align == Qt.AlignmentFlag.AlignLeft:
            box = QRectF(x, y - height / 2, target.width() - x, height)
        else:
            half = target.width() * 0.25
            box = QRectF(x - half, y - height / 2, half * 2, height)

        painter.drawText(
            box, int(align | Qt.AlignmentFlag.AlignVCenter), str(text)
        )

    painter.restore()


# ---------------------------------------------------------------------------
# بناء القيم من عقد حقيقي
# ---------------------------------------------------------------------------
def _text(value, fallback=""):
    return fallback if value in (None, "") else str(value)


def values_for_contract(contract_id, conn=None):
    """يبني قاموس ``{مفتاح الحقل: نصّه}`` من عقد قائم.

    المفاتيح هنا هي نفسها مفاتيح ``FIELDS``، فما يعيّنه المكتب في المحرّر يجد
    قيمته هنا حتماً — وحقلٌ بلا قيمة يُترك فارغاً على الورقة لا يُملأ بشرطة.
    """
    import datetime

    from ..core import money
    from ..repositories import contracts_repo
    from . import branding

    contract = contracts_repo.get(contract_id, conn=conn)
    if contract is None:
        raise TemplateError("العقد غير موجود.")

    symbol = settings_repo.symbol_of(contract["currency_code"], conn=conn)
    identity = branding.identity(conn=conn)

    def amount(minor):
        return money.format_amount(minor or 0, symbol)

    def column(key, default=""):
        return _text(contract[key] if key in contract.keys() else None, default)

    paid = contract["paid_amount"] if "paid_amount" in contract.keys() else 0
    balance = contract["balance_due"] if "balance_due" in contract.keys() else None
    if balance is None:
        balance = (contract["total_amount"] or 0) - (paid or 0)

    # المدّة والتعرفة تتبعان نمط الاحتساب: عقدٌ أُغلق بالساعة يطبع ساعاته
    # وتعرفة ساعته — وإلّا خرج من البرنامج الواحد عقدان متناقضان لعميل واحد،
    # وورقة المكتب هي التي يوقّعها الزبون.
    hourly = column("billing_mode") == "hourly"
    if hourly:
        duration_value = column("hours_count")
        rate_value = amount(contract["hourly_rate_snapshot"]
                            if "hourly_rate_snapshot" in contract.keys() else 0)
    else:
        duration_value = column("days_count")
        rate_value = amount(contract["daily_rate_snapshot"])

    return {
        "customer_name":          column("customer_name"),
        "customer_nationality":   column("customer_nationality"),
        "customer_national_id":   column("customer_national_id"),
        "customer_license":       column("customer_license_number"),
        "customer_license_expiry": column("customer_license_expiry"),
        "customer_license_issuer": column("customer_license_issuer"),
        "customer_dob":           column("customer_dob"),
        "customer_address":       column("customer_address"),
        "customer_phone":         column("customer_phone"),
        "customer_work_address":  column("customer_work_address"),
        "customer_phone_alt":     column("customer_phone_alt"),

        "vehicle_type":     ("%s %s" % (column("brand"), column("model"))).strip(),
        "vehicle_plate":    column("plate_number"),
        "vehicle_chassis":  column("chassis_number"),
        "vehicle_year":     column("year"),
        "vehicle_color":    column("color"),
        "vehicle_body_style": column("body_style"),
        "vehicle_odometer": column("start_odometer"),

        "contract_number":  column("contract_number"),
        "start_date":       column("start_date"),
        "end_date":         column("actual_end_date") or column("expected_end_date"),
        "days_count":       duration_value,
        "pickup_location":  column("pickup_location"),
        "allowed_area":       column("allowed_area"),
        "guarantees":         column("guarantees"),
        "departure_condition": column("departure_condition"),
        "renewed_until":      column("renewed_until"),
        "today":            datetime.date.today().isoformat(),

        "total_amount":   amount(contract["total_amount"]),
        "paid_amount":    amount(paid),
        "balance_amount": amount(balance),
        "daily_rate":     rate_value,

        "guarantor_name":        column("guarantor_name"),
        "guarantor_nationality": column("guarantor_nationality"),
        "guarantor_passport":    column("guarantor_passport"),
        "guarantor_address":     column("guarantor_address"),
        "guarantor_phone":       column("guarantor_phone"),
        "guarantor_work_address": column("guarantor_work_address"),

        "office_name":      identity["name"],
        "office_phone":     identity["phone"],
        "office_phone_alt": identity["phone_alt"],
        "office_address":   identity["address"],
        "office_register":  identity["commercial_register"],
    }


def sample_values():
    """قيم وهمية لزرّ «تجربة الطباعة» في المحرّر.

    الأسماء عربية طويلة عمداً: نصّ قصير يُخفي أن الحقل ضيّق أو متداخل مع جاره،
    فلا يكتشف المكتب الخلل إلّا على أول عقد حقيقي.
    """
    import datetime

    today = datetime.date.today()
    return {
        "customer_name": "محمد عبد الرحمن الشريف",
        "customer_nationality": "ليبي",
        "customer_national_id": "119876543210",
        "customer_license": "LC-4455",
        "customer_license_expiry": (today.replace(year=today.year + 2)).isoformat(),
        "customer_license_issuer": "إدارة المرور — طرابلس",
        "customer_dob": "1988-04-17",
        "customer_address": "طرابلس — شارع الجمهورية",
        "customer_phone": "0912345678",
        "customer_work_address": "طرابلس — شارع عمر المختار، مبنى الرواد",
        "customer_phone_alt": "0925556677",

        "vehicle_type": "تويوتا كورولا",
        "vehicle_plate": "5-12345",
        "vehicle_chassis": "JTDBR32E030098765",
        "vehicle_year": "2022",
        "vehicle_color": "أبيض",
        "vehicle_body_style": "صالون",
        "vehicle_odometer": "42000",

        "contract_number": "CR-%d-0001" % today.year,
        "start_date": today.isoformat(),
        "end_date": (today + datetime.timedelta(days=7)).isoformat(),
        "days_count": "7",
        "pickup_location": "مقرّ المكتب",
        "allowed_area": "طرابلس ومصراتة والزاوية فقط",
        "guarantees": "عدد (2) شيكات مؤجَّلة + جواز سفر",
        "departure_condition": "خدش في الرفرف الأيمن، الإطارات سليمة، الوقود نصف خزّان",
        "renewed_until": (today + datetime.timedelta(days=14)).isoformat(),
        "today": today.isoformat(),

        "total_amount": "900.00 د.ل",
        "paid_amount": "400.00 د.ل",
        "balance_amount": "500.00 د.ل",
        "daily_rate": "150.00 د.ل",

        "guarantor_name": "علي أبو بكر الفيتوري",
        "guarantor_nationality": "ليبي",
        "guarantor_passport": "P-778899",
        "guarantor_address": "طرابلس — حي الأندلس",
        "guarantor_phone": "0913334455",
        "guarantor_work_address": "طرابلس — سوق الجمعة",

        "office_name": "مكتب النور لإيجار السيارات",
        "office_phone": "0918887777",
        "office_phone_alt": "0925556677",
        "office_address": "طرابلس — شارع الشط",
        "office_register": "TR-2024-118834",
    }

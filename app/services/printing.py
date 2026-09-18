# -*- coding: utf-8 -*-
"""الطباعة المباشرة على طابعة ويندوز الافتراضية، وأرشفة ما يُطبع.

**ما الذي يحلّه هذا الملف؟** كانت المنظومة تُنتج ملف PDF وتتركه للموظّف: يفتحه،
ثم Ctrl+P، ثم يختار الطابعة، ثم يضغط طباعة. أربع خطوات في مكتب يستقبل زبوناً
كل ربع ساعة. وصار الأمر ضغطةً واحدة: يُحفظ العقد في الأرشيف ويخرج من الطابعة.

**ولماذا تُطبع صورةُ الملف المؤرشف لا المستندُ من جديد؟** لأن ما يوقّعه الزبون
يجب أن يكون **نفسه** ما في الأرشيف حرفاً بحرف. توليد المستند مرّتين — مرّة
للحفظ ومرّة للطباعة — يفتح باباً لاختلافهما ولو في تاريخ الطباعة أسفل الورقة.

**ولماذا لا يُعدّ غيابُ الطابعة خطأً؟** لأن المنظومة تعمل على أجهزة بلا طابعة:
حاسوب المالك في البيت، وجهاز يُجرَّب عليه قبل الشراء. فالعقد يُحفظ في كل حال،
وتقول الرسالة أين حُفظ.
"""

import datetime
import pathlib

from .. import config
from ..repositories import settings_repo

KEY_ARCHIVE_DIR = "archive_dir"


class PrintingError(Exception):
    """تعذّرت الطباعة، برسالة عربية تصلح للعرض."""


# ---------------------------------------------------------------------------
# مجلد الأرشيف
# ---------------------------------------------------------------------------
def archive_root(conn=None):
    """المجلد الذي يختاره المكتب لحفظ ما يُطبع، وافتراضه مجلد التصدير."""
    chosen = (settings_repo.get(KEY_ARCHIVE_DIR, "", conn=conn) or "").strip()
    return pathlib.Path(chosen) if chosen else pathlib.Path(config.EXPORTS_DIR)


def archive_path(name, when=None, conn=None):
    """مسار ملف داخل الأرشيف، منظَّماً بالسنة ثم الشهر.

    مكتبٌ في سنته الثالثة لا يُفيده مجلد فيه ألف ملف: البحث عن عقد شهرٍ بعينه
    يصير تصفّحاً لا فتحَ مجلد. والتنظيم بالتاريخ هو ما يفعله المحاسب بالورق.
    """
    when = when or datetime.date.today()
    directory = archive_root(conn=conn) / ("%04d" % when.year) / ("%02d" % when.month)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / name


def set_archive_root(path, conn=None):
    """يضبط مجلد الأرشيف بعد التحقّق أنه **قابل للكتابة فعلاً**.

    لا يكفي أن يوجد المجلد: مجلدٌ على قرص شبكة انقطع، أو مسار بلا صلاحية، كان
    يُقبل هنا ثم يُفشل أول طباعة — بعد أن يكون الزبون واقفاً ينتظر ورقته.
    """
    path = (str(path) or "").strip()
    if not path:
        settings_repo.set_value(KEY_ARCHIVE_DIR, "", conn=conn)
        return pathlib.Path(config.EXPORTS_DIR)

    directory = pathlib.Path(path).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".car_rental_write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise PrintingError(
            "تعذّرت الكتابة في المجلد المختار:\n%s\n%s" % (directory, error)
        )

    settings_repo.set_value(KEY_ARCHIVE_DIR, str(directory), conn=conn)
    return directory


# ---------------------------------------------------------------------------
# الطابعة
# ---------------------------------------------------------------------------
def default_printer_name():
    """اسم الطابعة الافتراضية في النظام، أو ``None`` إن لم تكن هناك طابعة."""
    from PyQt6.QtPrintSupport import QPrinterInfo

    info = QPrinterInfo.defaultPrinter()
    if info is None or info.isNull():
        # لا طابعة افتراضية: تُجرَّب أول طابعة مثبَّتة. مكتبٌ له طابعة واحدة
        # لم يجعلها افتراضية أَولى بأن تعمل من أن تُردّ خائباً.
        available = QPrinterInfo.availablePrinters()
        if not available:
            return None
        info = available[0]
    return info.printerName() or None


def print_pdf(path, printer_name=None):
    """يطبع ملف PDF على الطابعة الافتراضية بلا أي حوار.

    يُرجع اسم الطابعة التي طبعت، أو ``None`` إن لم توجد طابعة — وهذه ليست
    حالة خطأ بل حالة جهاز بلا طابعة، يتصرّف نداؤها بحسبها.
    """
    from PyQt6.QtCore import QRectF, QSizeF
    from PyQt6.QtGui import QPainter
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

    path = pathlib.Path(path)
    if not path.is_file():
        raise PrintingError("ملف الطباعة غير موجود: %s" % path)

    printer_name = printer_name or default_printer_name()
    if not printer_name:
        return None

    info = QPrinterInfo.printerInfo(printer_name)
    if info.isNull():
        raise PrintingError("الطابعة «%s» غير موجودة." % printer_name)

    document = QPdfDocument(None)
    if document.load(str(path)) != QPdfDocument.Error.None_:
        raise PrintingError("تعذّرت قراءة ملف الطباعة: %s" % path.name)

    printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)

    painter = QPainter()
    if not painter.begin(printer):
        raise PrintingError(
            "تعذّر فتح الطابعة «%s». تأكّد أنها موصولة وجاهزة." % printer_name
        )

    try:
        target = printer.pageRect(QPrinter.Unit.DevicePixel)
        for page in range(document.pageCount()):
            if page:
                printer.newPage()

            size = document.pagePointSize(page)
            if size.isEmpty():
                continue

            # احتواءٌ بنسبة محفوظة: تمديد الصفحة إلى حوافّ الورقة يشوّه
            # العقد، وعقدٌ مطبوع بنسبة خاطئة يبدو مزوَّراً لا مضبوطاً.
            factor = min(target.width() / size.width(),
                         target.height() / size.height())
            drawn = QSizeF(size.width() * factor, size.height() * factor)
            image = document.render(page, drawn.toSize())

            painter.drawImage(
                QRectF(target.x() + (target.width() - drawn.width()) / 2,
                       target.y() + (target.height() - drawn.height()) / 2,
                       drawn.width(), drawn.height()),
                image,
            )
    finally:
        painter.end()

    return printer_name

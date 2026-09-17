# -*- coding: utf-8 -*-
"""عناصر واجهة مشتركة تُستخدم في كل الصفحات.

وجودها في ملف واحد يمنع تكرار الشيفرة، ويضمن أن الجداول والبطاقات والرسائل
تبدو متطابقة في كل شاشات التطبيق.
"""

import re

from PyQt6.QtCore import QDate, Qt, QTime
from PyQt6.QtGui import QGuiApplication, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTableView, QTimeEdit, QVBoxLayout, QWidget,
)

from ...core import money

# علامة LEFT-TO-RIGHT MARK: تُدرج حول التواريخ والأرقام المفصولة بشرطات.
# بدونها ينقلب «2026-09-01» بصرياً إلى «01-09-2026» داخل فقرة عربية، لأن
# الشرطة محرف محايد يأخذ اتجاه الفقرة. اللبس هنا ليس تجميلياً: تاريخ عقد
# مقلوب خطأ حقيقي.
LRM = "‎"

# يلتقط كل مجموعة أرقام تفصلها شرطات: التواريخ «2026-09-01»، وأرقام اللوحات
# «5-12345»، وأرقام الوثائق. كلّها تنقلب بصرياً في فقرة عربية لأن الشرطة محرف
# محايد يأخذ اتجاه الفقرة — ولوحةٌ مقلوبة في عقد خطأ كخطأ التاريخ المقلوب.
_LTR_RUN_PATTERN = re.compile(
    r"\d+(?:-\d+)+(?:[ T]\d{2}:\d{2}(?::\d{2})?)?"
)

STATUS_BADGE_IDS = {
    "available": "badgeAvailable",
    "rented": "badgeRented",
    "maintenance": "badgeMaintenance",
    "paid": "badgeAvailable",
    "deposit": "badgeRented",
    "due": "badgeDue",
    "open": "badgeRented",
    "closed": "badgeAvailable",
    "cancelled": "badgeDue",
}


def fix_dates(text):
    """يحيط كل تاريخ أو رقم لوحة بعلامة LRM فيُعرض بترتيبه الصحيح.

    >>> fix_dates("من 2026-09-01 إلى 2026-09-14")   # يُعرض: من 2026-09-01 إلى 2026-09-14
    >>> fix_dates("اللوحة 5-12345")                  # يُعرض: اللوحة 5-12345 لا 12345-5
    """
    if not text:
        return text
    return _LTR_RUN_PATTERN.sub(lambda match: LRM + match.group(0) + LRM, str(text))


# ---------------------------------------------------------------------------
# رسائل موحّدة
# ---------------------------------------------------------------------------
def show_error(parent, message, title="خطأ"):
    QMessageBox.critical(parent, title, str(message))


def show_info(parent, message, title="تمّت العملية"):
    QMessageBox.information(parent, title, str(message))


def show_warning(parent, message, title="تنبيه"):
    QMessageBox.warning(parent, title, str(message))


def confirm(parent, message, title="تأكيد"):
    """سؤال تأكيد بأزرار عربية. الافتراضي «لا» فلا يُحذف شيء بضغطة عابرة."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(str(message))

    yes = box.addButton("نعم", QMessageBox.ButtonRole.YesRole)
    box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()

    return box.clickedButton() is yes


# ---------------------------------------------------------------------------
# حوارات النماذج
# ---------------------------------------------------------------------------
# نسبة من ارتفاع الشاشة المتاح لا يتجاوزها حوار مهما طال نموذجه.
_MAX_HEIGHT_RATIO = 0.85


class FormDialog(QDialog):
    """حوار نموذج: محتوًى قابل للتمرير وصفّ أزرار مثبَّت أسفله.

    وُجد لأن الحوارات كانت تضع نموذجها مباشرةً في تخطيط رأسي بلا حدّ لارتفاعه:
    على شاشة محمول (٧٦٨ بكسل) يتجاوز حوار السيارة ارتفاع الشاشة، **فيسقط زرّ
    الحفظ تحت حافّتها ولا يوجد ما يُمرَّر به إليه** — فلا يستطيع الموظّف حفظ
    عقد إلّا بضغط Enter عن غير علم. وهذا يعطّل المنظومة لا يشوّهها.

    الاستعمال:

        class VehicleDialog(FormDialog):
            def __init__(self, parent=None):
                super().__init__(parent, title="إضافة سيارة", width=520)
                self.form.addRow("الماركة", self.brand)   # يُمرَّر
                self.add_buttons(save_text="حفظ", on_save=self._save)
    """

    def __init__(self, parent=None, title="", width=520):
        super().__init__(parent)
        if title:
            self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        # التمرير الأفقي يعني نموذجاً أضيق من محتواه: يُمنع ليتّسع العرض بدله
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._content = QWidget()
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(18, 18, 18, 12)
        self.body.setSpacing(12)

        self.form = QFormLayout()
        self.form.setSpacing(10)
        # تسميات تلتفّ بدل أن تدفع الحوار عرضاً على الشاشات الصغيرة
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.body.addLayout(self.form)

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

        # صفّ الأزرار **خارج** منطقة التمرير فلا يغيب مهما طال النموذج
        self._buttons_bar = QWidget()
        self._buttons_bar.setObjectName("dialogButtons")
        self.buttons = QHBoxLayout(self._buttons_bar)
        self.buttons.setContentsMargins(18, 10, 18, 14)
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        outer.addWidget(self._buttons_bar)

        self.save_button = None

    # ------------------------------------------------------------------
    def add_widget(self, widget):
        """يضيف عنصراً تحت صفوف النموذج (بطاقة تسعيرة، تلميح، تحذير…)."""
        self.body.addWidget(widget)
        return widget

    def add_buttons(self, save_text="حفظ", on_save=None, cancel_text="إلغاء",
                    extra=()):
        """يبني صفّ الأزرار. زرّ الحفظ افتراضي فيعمل Enter بقصد لا بالصدفة."""
        for widget in extra:
            self.buttons.addWidget(widget)

        save = primary_button(save_text)
        save.setDefault(True)
        save.setAutoDefault(True)
        if on_save is not None:
            save.clicked.connect(on_save)
        self.buttons.addWidget(save)

        cancel = QPushButton(cancel_text)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.buttons.addWidget(cancel)

        self.save_button = save
        return save

    # ------------------------------------------------------------------
    def showEvent(self, event):
        """يحدّ ارتفاع الحوار بالشاشة قبل ظهوره، فلا يخرج شيء عن حدودها."""
        super().showEvent(event)
        self._fit_to_screen()

    def _fit_to_screen(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        max_height = int(available.height() * _MAX_HEIGHT_RATIO)
        max_width = int(available.width() * _MAX_HEIGHT_RATIO)

        wanted = self.sizeHint()
        height = min(wanted.height(), max_height)
        width = min(max(wanted.width(), self.minimumWidth()), max_width)

        self.setMaximumHeight(max_height)
        self.resize(width, height)

        # التوسيط بعد تغيير المقاس: حوار يُفتح نصفه خارج الشاشة لا يُستعمل
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())


# ---------------------------------------------------------------------------
# عناصر بنائية
# ---------------------------------------------------------------------------
def scrollable_body(page, margins=(22, 20, 22, 20), spacing=14):
    """يبني جسم صفحة **قابلاً للتمرير** ويُرجع تخطيطه.

    تُستعمل بدل ``QVBoxLayout(self)`` في الصفحات التي يتجاوز محتواها ارتفاع
    شاشة صغيرة: لم تكن في المنظومة صفحة واحدة تُمرَّر، فما نزل تحت حافّة
    النافذة كان **يختفي بلا شريط ولا أثر** — واصطدم بذلك صاحب المكتب في
    الإعدادات فلم يبلغ أزرار الحفظ أسفلها.

    ``setWidgetResizable(True)`` يجعل المحتوى يملأ المساحة حين تتّسع ويُمرَّر
    حين تضيق، فلا تنكسر معاملات التمدّد في الصفحات التي تنتهي بجدول يملأ ما
    تحته. وبلا إطار: منطقة التمرير وسيلةٌ لا تُرى.

    ولا تُستعمل في صفحات الجداول: الجدول يُمرَّر داخلياً، ولفّه هنا يُنتج
    شريطَي تمرير متداخلين — علاجٌ يُحدث داءً.
    """
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    area = QScrollArea(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    outer.addWidget(area)

    content = QWidget()
    area.setWidget(content)

    layout = QVBoxLayout(content)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


class Card(QFrame):
    """بطاقة بيضاء بحواف دائرية تحتضن مجموعة عناصر."""

    def __init__(self, parent=None, spacing=10, margins=(16, 16, 16, 16)):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setSpacing(spacing)
        self.body.setContentsMargins(*margins)


class StatCard(Card):
    """بطاقة إحصائية: قيمة كبيرة فوق عنوان صغير — تغذّي لوحة المعلومات."""

    def __init__(self, label, value="0", hint="", accent="#2f6fed", parent=None):
        super().__init__(parent, spacing=2, margins=(16, 14, 16, 14))

        self.value_label = QLabel(str(value))
        self.value_label.setObjectName("statCardValue")
        self.value_label.setStyleSheet("color: %s;" % accent)

        self.title_label = QLabel(label)
        self.title_label.setObjectName("statCardLabel")

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("statCardHint")
        self.hint_label.setVisible(bool(hint))

        self.body.addWidget(self.value_label)
        self.body.addWidget(self.title_label)
        self.body.addWidget(self.hint_label)

    def set_value(self, value, hint=None):
        self.value_label.setText(str(value))
        if hint is not None:
            self.hint_label.setText(str(hint))
            self.hint_label.setVisible(bool(hint))


class PageHeader(QWidget):
    """ترويسة صفحة: عنوان ووصف على اليمين، وأزرار إجراءات على اليسار."""

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        texts = QVBoxLayout()
        texts.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))

        texts.addWidget(self.title_label)
        texts.addWidget(self.subtitle_label)

        layout.addLayout(texts)
        layout.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, button):
        self.actions.addWidget(button)
        return button

    def set_subtitle(self, text):
        self.subtitle_label.setText(fix_dates(text))
        self.subtitle_label.setVisible(bool(text))


class DataTable(QTableView):
    """جدول للقراءة فقط بإعدادات موحّدة: صفّ كامل، تلوين متناوب، بلا تحرير."""

    def __init__(self, headers, parent=None, stretch_column=0):
        super().__init__(parent)
        self._headers = list(headers)

        self.model_ = QStandardItemModel(0, len(self._headers), self)
        self.model_.setHorizontalHeaderLabels([label for _, label in self._headers])
        self.setModel(self.model_)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setHighlightSections(False)
        # ضبط الأعمدة يدوياً بعد كل تعبئة (انظر ``_fit_columns``).
        # الأوضاع التلقائية (ResizeToContents / Stretch) قُيّست فعلياً فوجدناها
        # تحسب العرض على رأس العمود وحده قبل وصول الصفوف، فتظهر الأسماء
        # مقصوصة «محم…»، ولذلك اعتُمد الضبط الصريح.
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)   # الفائض يُوزَّع في ``_fit_columns``
        header.setMinimumSectionSize(60)
        self._stretch_column = stretch_column
        self.verticalHeader().setDefaultSectionSize(34)

    def fill(self, rows, formatter=None):
        """يملأ الجدول. ``formatter`` دالة (صفّ، مفتاح) ← نصّ العرض."""
        self.model_.removeRows(0, self.model_.rowCount())

        for row in rows:
            items = []
            for key, _ in self._headers:
                if formatter is not None:
                    text = formatter(row, key)
                elif hasattr(row, "keys"):
                    text = row[key] if key in row.keys() else ""
                else:
                    text = getattr(row, key, "")
                item = QStandardItem("" if text is None else fix_dates(str(text)))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                items.append(item)

            # معرّف الصفّ يُخزَّن في أول خلية فيُسترجع عند الاختيار.
            # الصفوف قد تكون سجلّات قاعدة بيانات أو كائنات (مثل التنبيهات)،
            # فيُقرأ المعرّف من أيّهما بلا افتراض نوع.
            identifier = None
            if hasattr(row, "keys") and "id" in row.keys():
                identifier = row["id"]
            elif hasattr(row, "subject_id"):
                identifier = row.subject_id
            if identifier is not None:
                items[0].setData(identifier, Qt.ItemDataRole.UserRole)
            self.model_.appendRow(items)

        self._fit_columns()
        return self.model_.rowCount()

    def _fit_columns(self):
        """يضبط عرض كل عمود على محتواه، ثم يمنح الفائض للعمود الرئيسي."""
        self.resizeColumnsToContents()

        columns = self.model_.columnCount()
        if not columns:
            return

        total = sum(self.columnWidth(i) for i in range(columns))
        spare = self.viewport().width() - total

        if spare > 0 and 0 <= self._stretch_column < columns:
            self.setColumnWidth(
                self._stretch_column, self.columnWidth(self._stretch_column) + spare
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.model_.rowCount():
            self._fit_columns()

    def selected_id(self):
        """معرّف الصفّ المختار، أو None إن لم يُختر شيء."""
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model_.item(indexes[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def selected_row_index(self):
        indexes = self.selectionModel().selectedRows()
        return indexes[0].row() if indexes else None


# ---------------------------------------------------------------------------
# حقول إدخال جاهزة
# ---------------------------------------------------------------------------
def search_box(placeholder="بحث…"):
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setClearButtonEnabled(True)
    field.setMinimumWidth(260)
    return field


def money_field(maximum=10_000_000.0):
    """حقل مبلغ: منزلتان عشريتان، ولا يقبل السالب."""
    field = QDoubleSpinBox()
    field.setDecimals(2)
    field.setMaximum(maximum)
    field.setMinimum(0.0)
    field.setSingleStep(10.0)
    field.setAlignment(Qt.AlignmentFlag.AlignRight)
    return field


def date_field(default=None):
    """حقل تاريخ ميلادي بصيغة YYYY-MM-DD.

    اتجاه الحقل يُضبط يساراً-إلى-يمين رغم أن الواجهة كلّها عربية: التاريخ
    المفصول بشرطات داخل سياق RTL ينقلب بصرياً فيظهر 2026-09-01 على هيئة
    01-09-2026، وهو لبس خطير في عقد إيجار.
    """
    field = QDateEdit()
    # الترتيب مقصود: Qt يعكس أقسام صيغة التاريخ تلقائياً في الواجهات RTL،
    # فيصير yyyy-MM-dd معروضاً dd-MM-yyyy. ضبط الاتجاه **قبل** الصيغة يمنع ذلك.
    field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    field.setDisplayFormat("yyyy-MM-dd")
    field.setCalendarPopup(True)
    field.setAlignment(Qt.AlignmentFlag.AlignCenter)
    field.setDate(default or QDate.currentDate())
    return field


def time_field(default="12:00"):
    """حقل وقت بصيغة 24 ساعة.

    الاتجاه يساراً-إلى-يمين للسبب نفسه الذي في حقل التاريخ: النقطتان محرف
    محايد ينقلب في سياق عربي فيصير 08:30 معروضاً 30:08.
    """
    field = QTimeEdit()
    field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    field.setDisplayFormat("HH:mm")
    field.setAlignment(Qt.AlignmentFlag.AlignCenter)
    field.setTime(QTime.fromString(str(default or "12:00"), "HH:mm"))
    return field


def combo(items=(), parent=None):
    """قائمة منسدلة: ``items`` أزواج (القيمة، النص المعروض)."""
    box = QComboBox(parent)
    for value, label in items:
        box.addItem(str(label), value)
    return box


def primary_button(text):
    button = QPushButton(text)
    button.setObjectName("primary")
    return button


def danger_button(text):
    button = QPushButton(text)
    button.setObjectName("danger")
    return button


def badge(text, kind):
    """شارة ملوّنة تعبّر عن حالة."""
    label = QLabel(text)
    label.setObjectName(STATUS_BADGE_IDS.get(kind, "badgeMaintenance"))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def format_money(minor, symbol=""):
    return money.format_amount(minor, symbol)

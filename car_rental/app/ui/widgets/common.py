# -*- coding: utf-8 -*-
"""عناصر واجهة مشتركة تُستخدم في كل الصفحات.

وجودها في ملف واحد يمنع تكرار الشيفرة، ويضمن أن الجداول والبطاقات والرسائل
تبدو متطابقة في كل شاشات التطبيق.
"""

import re

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableView,
    QVBoxLayout, QWidget,
)

from ...core import money

# علامة LEFT-TO-RIGHT MARK: تُدرج حول التواريخ والأرقام المفصولة بشرطات.
# بدونها ينقلب «2026-09-01» بصرياً إلى «01-09-2026» داخل فقرة عربية، لأن
# الشرطة محرف محايد يأخذ اتجاه الفقرة. اللبس هنا ليس تجميلياً: تاريخ عقد
# مقلوب خطأ حقيقي.
LRM = "‎"

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")

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
    """يحيط كل تاريخ في النص بعلامة LRM فيُعرض بترتيبه الصحيح.

    >>> fix_dates("من 2026-09-01 إلى 2026-09-14")   # يُعرض: من 2026-09-01 إلى 2026-09-14
    """
    if not text:
        return text
    return _DATE_PATTERN.sub(lambda match: LRM + match.group(0) + LRM, str(text))


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
# عناصر بنائية
# ---------------------------------------------------------------------------
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
                else:
                    text = row[key] if key in row.keys() else ""
                item = QStandardItem("" if text is None else fix_dates(str(text)))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                items.append(item)

            # معرّف الصفّ يُخزَّن في أول خلية فيُسترجع عند الاختيار
            if "id" in row.keys():
                items[0].setData(row["id"], Qt.ItemDataRole.UserRole)
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

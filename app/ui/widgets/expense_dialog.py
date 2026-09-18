# -*- coding: utf-8 -*-
"""حوار إدخال مصروف على سيارة — «إضافة مصروف / صيانة».

يُفتح من موضعين، ولذلك وُضع في العناصر المشتركة لا داخل صفحة بعينها:

    • من **ملفّ السيارة** في شاشة السيارات: السيارة معروفة فتُثبَّت.
    • من **تقرير أداء وربحية السيارات**: تُختار السيارة من قائمة.

والنموذج قصير عن قصد: خمسة حقول لا أكثر. دفترُ تكاليفٍ يطلب عشرة حقول لكل
علبة زيت دفترٌ لا يُملأ، وتقريرُ ربحيةٍ فوق دفتر فارغ لا يقول شيئاً.
"""

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QLabel, QPlainTextEdit

from ... import config
from ...core import money
from ...repositories import expenses_repo, settings_repo, vehicles_repo
from .common import (
    FormDialog, combo, date_field, money_field, show_error,
)


def vehicle_items(conn=None):
    """قائمة السيارات كما تُعرض في المنتقي: «الماركة الموديل — اللوحة»."""
    return [
        (row["id"], "%s %s — %s" % (row["brand"], row["model"], row["plate_number"]))
        for row in vehicles_repo.search(limit=2000, conn=conn)
    ]


def _currency_items():
    return [(row["code"], "%s (%s)" % (row["name_ar"], row["symbol"]))
            for row in settings_repo.list_currencies()]


class ExpenseDialog(FormDialog):
    """إدخال مصروف جديد أو تعديل مصروف مسجَّل.

    ``vehicle``  صفّ السيارة حين يُفتح الحوار من ملفّها — فتُثبَّت ولا تُختار.
    ``expense``  صفّ المصروف عند التعديل.
    """

    def __init__(self, parent=None, vehicle=None, expense=None):
        super().__init__(
            parent,
            title="تعديل مصروف" if expense else "إضافة مصروف / صيانة",
            width=480,
        )
        self._vehicle = vehicle
        self._expense = expense

        form = self.form

        # --- السيارة ---
        # حين يُفتح الحوار من ملفّ سيارة بعينها تُعرض ثابتةً لا قائمةً: اختيارٌ
        # مفتوح هنا يفتح باب تسجيل المصروف على السيارة الخطأ بضغطة واحدة،
        # ولا شيء في التقرير بعدها يكشف الخطأ.
        self.vehicle = None
        if vehicle is None:
            self.vehicle = combo(vehicle_items())
            form.addRow("السيارة *", self.vehicle)
        else:
            fixed = QLabel("%s %s — %s" % (vehicle["brand"], vehicle["model"],
                                           vehicle["plate_number"]))
            fixed.setObjectName("sectionTitle")
            form.addRow("السيارة", fixed)

        # --- تفاصيل المصروف ---
        self.expense_type = combo(list(config.EXPENSE_TYPE_LABELS.items()))
        self.amount = money_field()
        self.currency = combo(_currency_items())
        self.date = date_field()
        # لا مصروف بتاريخ لاحق لليوم: تكلفةٌ لم تُصرف بعد تُفسد حساب الربح،
        # والمنع في الحقل نفسه أوضح من رسالة خطأ بعد الضغط على «حفظ».
        self.date.setMaximumDate(QDate.currentDate())

        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)
        self.notes.setPlaceholderText("اسم الورشة، رقم الفاتورة، تفاصيل القطعة…")

        form.addRow("نوع المصروف *", self.expense_type)
        form.addRow("القيمة *", self.amount)
        form.addRow("العملة", self.currency)
        form.addRow("التاريخ *", self.date)
        form.addRow("ملاحظات", self.notes)

        hint = QLabel(
            "يدخل هذا المبلغ مباشرةً في حساب ربحية السيارة: "
            "صافي الربح = إجمالي الإيرادات − إجمالي المصروفات.\n"
            "وتكاليف الصيانة المسجَّلة في شاشة «الصيانة والمخالفات» محسوبة "
            "تلقائياً ضمن التقرير، فلا حاجة إلى إعادة إدخالها هنا."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.add_buttons(save_text="حفظ", on_save=self._save)

        if expense is not None:
            self._load(expense)
        elif vehicle is not None:
            self._select_currency(vehicle["currency_code"])

    # ------------------------------------------------------------------
    def _select_currency(self, code):
        index = self.currency.findData(code)
        if index >= 0:
            self.currency.setCurrentIndex(index)

    def _load(self, expense):
        index = self.expense_type.findData(expense["expense_type"])
        if index >= 0:
            self.expense_type.setCurrentIndex(index)

        self.amount.setValue(float(money.to_major(expense["amount"])))
        self._select_currency(expense["currency_code"])
        self.date.setDate(QDate.fromString(str(expense["date"]), "yyyy-MM-dd"))
        self.notes.setPlainText(expense["notes"] or "")

        if self.vehicle is not None:
            index = self.vehicle.findData(expense["vehicle_id"])
            if index >= 0:
                self.vehicle.setCurrentIndex(index)
            self.vehicle.setEnabled(False)   # نقل مصروف بين سيارتين ليس تعديلاً

    # ------------------------------------------------------------------
    def _vehicle_id(self):
        if self._vehicle is not None:
            return self._vehicle["id"]
        return self.vehicle.currentData() if self.vehicle is not None else None

    def _save(self):
        vehicle_id = self._vehicle_id()
        if vehicle_id is None:
            show_error(self, "اختر السيارة أولاً.")
            return

        amount = money.to_minor(self.amount.value())
        date = self.date.date().toString("yyyy-MM-dd")
        notes = self.notes.toPlainText().strip() or None

        try:
            if self._expense is not None:
                expenses_repo.update_expense(
                    self._expense["id"],
                    self.expense_type.currentData(),
                    amount,
                    date,
                    notes=notes,
                    currency_code=self.currency.currentData(),
                )
            else:
                expenses_repo.add_expense(
                    vehicle_id,
                    self.expense_type.currentData(),
                    amount,
                    date=date,
                    notes=notes,
                    currency_code=self.currency.currentData(),
                )
        except Exception as error:
            show_error(self, error)
            return

        self.accept()

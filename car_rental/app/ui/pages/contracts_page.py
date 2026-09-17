# -*- coding: utf-8 -*-
"""صفحة العقود: الإنشاء والإغلاق والتمديد والدفعات وطباعة العقد.

حوار إنشاء العقد يعرض **تسعيرة لحظية** تتحدّث مع كل تغيير في التواريخ أو
الخصم، فيرى الموظّف القيمة النهائية قبل أن يضغط «حفظ»، ولا يُفاجأ العميل.
"""

import datetime

from PyQt6.QtCore import QDate, Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ... import config
from ...core import money, session
from ...repositories import (
    contracts_repo, customers_repo, payments_repo, settings_repo, vehicles_repo,
)
from ...services import alerts, contract_pdf, pricing, rental_service
from ..widgets.common import (
    Card, DataTable, FormDialog, PageHeader, combo, confirm, date_field,
    fix_dates, money_field, primary_button, search_box, show_error, show_info,
    time_field,
)


def _customer_label(row):
    """اسم العميل مع عدد عقوده — فيُعرف المتكرّر من القائمة مباشرةً."""
    count = row["contracts_count"] if "contracts_count" in row.keys() else 0
    suffix = " — %d عقود سابقة" % count if count else ""
    return "%s — %s%s" % (row["full_name"], row["phone"], suffix)


def _vehicle_label(row):
    """وصف السيارة مع بيان انشغالها الحالي إن وُجد."""
    title = "%s %s — %s" % (row["brand"], row["model"], row["plate_number"])
    busy_until = row["busy_until"] if "busy_until" in row.keys() else None
    if busy_until:
        return "%s (مشغولة حتى %s)" % (title, busy_until)
    return title


class NewContractDialog(FormDialog):
    """حوار فتح عقد إيجار جديد مع تسعيرة لحظية."""

    def __init__(self, parent=None, preset=None):
        super().__init__(
            parent,
            title="تجديد العقد" if preset else "عقد إيجار جديد",
            width=580,
        )

        self._vehicle = None
        self._insurance_alert = None
        self.created_id = None
        preset = preset or {}

        form = self.form

        # العملاء مرتَّبون بالأكثر تعاملاً: من يتردّد على المكتب كثيراً يظهر أولاً
        # ولا يُبحث عنه في كل مرّة.
        #
        # والحقل **قابل للكتابة**: المكتب يستقبل زبوناً واقفاً أمامه، فيكتب اسمه
        # ويمضي في العقد، ثم يُكمل وثائقه. وإلزامه بتسجيل العميل كاملاً أولاً
        # يعطّل العمل ويدفعه إلى كتابة أرقام مُختلَقة.
        self.customer = combo(
            [(row["id"], _customer_label(row))
             for row in customers_repo.search(limit=2000, order_by="frequent")
             if not row["is_blacklisted"]]
        )
        self.customer.setEditable(True)
        self.customer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.customer.lineEdit().setPlaceholderText(
            "اكتب اسم العميل — إن كان جديداً يُسجَّل تلقائياً"
        )

        completer = QCompleter(
            [self.customer.itemText(i) for i in range(self.customer.count())], self
        )
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.customer.setCompleter(completer)
        self.customer.setCurrentIndex(-1)

        # كل السيارات غير الخاضعة للصيانة قابلة للحجز — المؤجَّرة اليوم تُحجَز
        # لفترة لاحقة، وهو جوهر عمل مكتب محدود عدد السيارات.
        self.vehicle = combo(
            [(row["id"], _vehicle_label(row)) for row in vehicles_repo.list_bookable()]
        )
        self.vehicle.currentIndexChanged.connect(self._on_vehicle_changed)

        self.start_date = date_field()
        self.start_time = time_field()
        self.end_date = date_field(QDate.currentDate().addDays(1))
        self.start_date.dateChanged.connect(self._recalculate)
        self.end_date.dateChanged.connect(self._recalculate)

        self.discount = money_field()
        self.discount.valueChanged.connect(self._recalculate)
        self.extra = money_field()
        self.extra.valueChanged.connect(self._recalculate)

        self.deposit = money_field()
        self.deposit_method = combo(list(config.PAYMENT_METHOD_LABELS.items()))

        self.odometer = QSpinBox()
        self.odometer.setRange(0, 5_000_000)
        self.odometer.setSuffix(" كم")

        self.pickup = QLineEdit()

        # الكفيل: تطلبه نماذج عقود المكاتب المطبوعة، ويتغيّر بين عقد وآخر
        # للعميل نفسه، فيُحفظ في العقد لا في ملفّ العميل.
        self.guarantor_name = QLineEdit()
        self.guarantor_nationality = QLineEdit()
        self.guarantor_passport = QLineEdit()
        self.guarantor_address = QLineEdit()

        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)

        form.addRow("العميل *", self.customer)
        form.addRow("السيارة *", self.vehicle)
        form.addRow("تاريخ الاستلام *", self.start_date)
        form.addRow("وقت الاستلام", self.start_time)
        form.addRow("تاريخ التسليم المتوقَّع *", self.end_date)
        form.addRow("خصم", self.discount)
        form.addRow("رسوم إضافية", self.extra)
        form.addRow("عربون مدفوع الآن", self.deposit)
        form.addRow("طريقة دفع العربون", self.deposit_method)
        form.addRow("قراءة العدّاد عند الاستلام", self.odometer)
        form.addRow("مكان الاستلام", self.pickup)
        form.addRow("اسم الكفيل", self.guarantor_name)
        form.addRow("جنسية الكفيل", self.guarantor_nationality)
        form.addRow("رقم جواز الكفيل", self.guarantor_passport)
        form.addRow("عنوان الكفيل", self.guarantor_address)
        form.addRow("ملاحظات", self.notes)

        # --- التسعيرة اللحظية ---
        self.quote_card = Card(margins=(14, 12, 14, 12), spacing=4)
        self.quote_label = QLabel("اختر سيارة وتواريخ لعرض التسعيرة.")
        self.quote_label.setWordWrap(True)
        self.quote_card.body.addWidget(self.quote_label)
        self.add_widget(self.quote_card)

        # تحذير التأمين: لا يمنع، لكنه لا يُخفي. تأجير سيارة بلا تأمين ساري
        # مسؤولية قانونية على المكتب، والقرار قراره لا قرار البرنامج.
        self.insurance_warning = QLabel("")
        self.insurance_warning.setWordWrap(True)
        self.insurance_warning.setStyleSheet(
            "background: #fee2e2; color: #b91c1c; border-radius: 8px; padding: 8px;"
        )
        self.insurance_warning.setVisible(False)
        self.add_widget(self.insurance_warning)

        self.add_buttons(save_text="حفظ العقد", on_save=self._save)

        # التجديد: نفس العميل ونفس السيارة، ويبدأ من انتهاء العقد السابق
        if preset:
            self._apply_preset(preset)

        if self.vehicle.count():
            self._on_vehicle_changed()
        else:
            self.quote_label.setText("⚠ لا توجد سيارات قابلة للحجز (كلّها في الصيانة).")
            if self.save_button is not None:
                self.save_button.setEnabled(False)

        # لا منع حين لا يوجد عملاء: اسم يُكتب في الحقل يصير عميلاً

    def _apply_preset(self, preset):
        for widget, key in ((self.customer, "customer_id"), (self.vehicle, "vehicle_id")):
            index = widget.findData(preset.get(key))
            if index >= 0:
                widget.setCurrentIndex(index)

        if preset.get("start_date"):
            start = QDate.fromString(preset["start_date"], "yyyy-MM-dd")
            self.start_date.setDate(start)
            self.end_date.setDate(start.addDays(int(preset.get("days") or 7)))
        if preset.get("start_time"):
            self.start_time.setTime(
                QTime.fromString(preset["start_time"], "HH:mm")
            )
        if preset.get("notes"):
            self.notes.setPlainText(preset["notes"])

    # ------------------------------------------------------------------
    def _on_vehicle_changed(self):
        vehicle_id = self.vehicle.currentData()
        self._vehicle = vehicles_repo.get(vehicle_id) if vehicle_id else None
        if self._vehicle:
            self.odometer.setValue(int(self._vehicle["odometer"] or 0))
        self._check_insurance()
        self._recalculate()

    def _check_insurance(self):
        """يُظهر تحذيراً إن كان تأمين السيارة منتهياً — ولا يمنع الحفظ."""
        self._insurance_alert = None
        if self._vehicle is None:
            self.insurance_warning.setVisible(False)
            return

        self._insurance_alert = alerts.vehicle_insurance_state(self._vehicle)
        if self._insurance_alert is None:
            self.insurance_warning.setVisible(False)
            return

        self.insurance_warning.setText(
            "⚠ %s\nتأجير سيارة بلا تأمين ساري مسؤولية على المكتب."
            % fix_dates(self._insurance_alert.message)
        )
        self.insurance_warning.setVisible(True)

    def _recalculate(self):
        if self._vehicle is None:
            return

        symbol = settings_repo.symbol_of(self._vehicle["currency_code"])
        try:
            estimate = pricing.quote(
                self.start_date.date().toString("yyyy-MM-dd"),
                self.end_date.date().toString("yyyy-MM-dd"),
                self._vehicle["daily_rate"],
                self._vehicle["weekly_rate"],
                money.to_minor(self.discount.value()),
                money.to_minor(self.extra.value()),
            )
        except ValueError as error:
            self.quote_label.setText("⚠ %s" % error)
            return

        self.deposit.setMaximum(float(money.to_major(estimate["total"])))
        self.quote_label.setText(
            "المدّة: %d يوم  |  السعر اليومي: %s  |  السعر الأسبوعي: %s\n"
            "قيمة الإيجار: %s   −  الخصم: %s   +  رسوم: %s\n"
            "الإجمالي المستحق: %s"
            % (
                estimate["days"],
                money.format_amount(self._vehicle["daily_rate"], symbol),
                money.format_amount(self._vehicle["weekly_rate"], symbol)
                if self._vehicle["weekly_rate"] else "—",
                money.format_amount(estimate["subtotal"], symbol),
                money.format_amount(estimate["discount"], symbol),
                money.format_amount(estimate["extra_charges"], symbol),
                money.format_amount(estimate["total"], symbol),
            )
        )

    def _resolve_customer(self):
        """يُرجع معرّف العميل، ويُنشئه من الاسم المكتوب إن كان جديداً.

        الترتيب مقصود: اختيارٌ من القائمة أولاً، فإن كتب الموظّف نصّاً حاولنا
        مطابقته باسم قائم (فلا يتكرّر العميل لأن الموظّف كتب اسمه بدل اختياره)،
        وإلّا أنشأناه بعد تأكيد صريح.
        """
        chosen = self.customer.currentData()
        typed = self.customer.currentText().strip()

        if chosen is not None and self.customer.currentText() == self.customer.itemText(
            self.customer.currentIndex()
        ):
            return chosen

        if not typed:
            show_error(self, "اكتب اسم العميل أو اختره من القائمة.")
            return None

        index = self.customer.findText(typed, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            return self.customer.itemData(index)

        # اسم مطابق لعميل مسجَّل ولو اختلفت صياغة السطر المعروض
        for existing in customers_repo.search(term=typed, limit=20):
            if (existing["full_name"] or "").strip() == typed:
                return existing["id"]

        if not confirm(
            self,
            "لا يوجد عميل بهذا الاسم.\n"
            "سيُسجَّل عميل جديد باسم «%s» ببيانات ناقصة، تُكملها لاحقاً من شاشة"
            " العملاء. متابعة؟" % typed,
        ):
            return None

        try:
            return customers_repo.create({"full_name": typed})
        except Exception as error:
            show_error(self, error)
            return None

    def _save(self):
        if self.vehicle.currentData() is None:
            show_error(self, "اختر السيارة.")
            return

        customer_id = self._resolve_customer()
        if customer_id is None:
            return

        if self._insurance_alert is not None and not confirm(
            self,
            "%s\nهل تريد إتمام العقد رغم ذلك؟" % self._insurance_alert.message,
            title="تأمين منتهٍ",
        ):
            return

        try:
            contract_id, number = rental_service.open_contract(
                customer_id=customer_id,
                vehicle_id=self.vehicle.currentData(),
                start_date=self.start_date.date().toString("yyyy-MM-dd"),
                expected_end_date=self.end_date.date().toString("yyyy-MM-dd"),
                start_time=self.start_time.time().toString("HH:mm"),
                discount=money.to_minor(self.discount.value()),
                extra_charges=money.to_minor(self.extra.value()),
                deposit_amount=money.to_minor(self.deposit.value()),
                deposit_method=self.deposit_method.currentData(),
                pickup_location=self.pickup.text().strip() or None,
                notes=self.notes.toPlainText().strip() or None,
                start_odometer=self.odometer.value(),
                guarantor={
                    "name": self.guarantor_name.text().strip(),
                    "nationality": self.guarantor_nationality.text().strip(),
                    "passport": self.guarantor_passport.text().strip(),
                    "address": self.guarantor_address.text().strip(),
                },
            )
        except Exception as error:
            show_error(self, error)
            return

        self.created_id = contract_id
        show_info(self, "تم إنشاء العقد برقم %s." % number)
        self.accept()


class CloseContractDialog(FormDialog):
    """حوار إغلاق عقد وإعادة حساب القيمة بالمدّة الفعلية."""
    def __init__(self, contract, parent=None):
        super().__init__(parent, title="إنهاء العقد %s" % contract["contract_number"], width=520)
        self._contract = contract


        form = self.form

        self.end_date = date_field()
        self.end_date.dateChanged.connect(self._preview)

        self.end_time = time_field(datetime.datetime.now().strftime("%H:%M"))
        self.end_time.timeChanged.connect(self._preview)

        # الإرجاع المبكّر يُحتسب بالساعة: من أعادها قبل الموعد بخمس ساعات لا
        # يَعدل أن يُحاسَب بيوم كامل.
        self.hourly = QCheckBox("احتساب المدّة بالساعة (للإرجاع المبكّر)")
        self.hourly.stateChanged.connect(self._preview)

        self.extra = money_field()
        self.extra.valueChanged.connect(self._preview)

        self.odometer = QSpinBox()
        self.odometer.setRange(0, 5_000_000)
        self.odometer.setSuffix(" كم")
        self.odometer.setValue(int(contract["start_odometer"] or 0))

        self.return_location = QLineEdit()
        self.note = QLineEdit()

        form.addRow("تاريخ التسليم الفعلي *", self.end_date)
        form.addRow("وقت التسليم", self.end_time)
        form.addRow("", self.hourly)
        form.addRow("رسوم إضافية (تأخير، وقود، أضرار)", self.extra)
        form.addRow("قراءة العدّاد عند التسليم", self.odometer)
        form.addRow("مكان التسليم", self.return_location)
        form.addRow("ملاحظة", self.note)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        card = Card(margins=(14, 12, 14, 12))
        card.body.addWidget(self.preview)
        self.add_widget(card)

        self.add_buttons(save_text="إغلاق العقد", on_save=self._save)

        self._preview()

    def _preview(self):
        symbol = settings_repo.symbol_of(self._contract["currency_code"])
        raw = contracts_repo.get_raw(self._contract["id"])
        hourly = self.hourly.isChecked()

        try:
            result = pricing.settlement(
                raw,
                self.end_date.date().toString("yyyy-MM-dd"),
                money.to_minor(self.extra.value()),
                actual_end_time=self.end_time.time().toString("HH:mm"),
                hourly=hourly,
            )
        except ValueError as error:
            self.preview.setText("⚠ %s" % error)
            return

        paid = int(self._contract["paid_amount"])
        difference = result["difference"]
        direction = "زيادة" if difference > 0 else ("نقص" if difference < 0 else "بلا تغيير")

        if hourly:
            duration = "%s (%d ساعة)" % (
                pricing.describe_duration(result["hours"]), result["hours"]
            )
        else:
            duration = "%d يوم" % result["days"]

        self.preview.setText(
            "المدّة الفعلية: %s — وكانت %d يوم\n"
            "القيمة النهائية: %s  (%s عن القيمة السابقة: %s)\n"
            "المدفوع: %s  |  المتبقّي بعد الإنهاء: %s"
            % (
                duration, self._contract["days_count"],
                money.format_amount(result["total"], symbol),
                direction, money.format_amount(abs(difference), symbol),
                money.format_amount(paid, symbol),
                money.format_amount(result["total"] - paid, symbol),
            )
        )

    def _save(self):
        try:
            result = rental_service.close_contract(
                self._contract["id"],
                actual_end_date=self.end_date.date().toString("yyyy-MM-dd"),
                extra_charges=money.to_minor(self.extra.value()),
                end_odometer=self.odometer.value() or None,
                return_location=self.return_location.text().strip() or None,
                note=self.note.text().strip() or None,
                actual_end_time=self.end_time.time().toString("HH:mm"),
                hourly=self.hourly.isChecked(),
            )
        except Exception as error:
            show_error(self, error)
            return

        symbol = settings_repo.symbol_of(self._contract["currency_code"])
        show_info(
            self,
            "أُغلق العقد وأصبحت السيارة متاحة.\nالمتبقّي على العميل: %s"
            % money.format_amount(result["balance_due"], symbol),
        )
        self.accept()


class EditContractDialog(FormDialog):
    """حوار تعديل عقد مفتوح: التواريخ والسيارة والخصم والرسوم.

    تبديل السيارة مسموح ومقصود: يحدث في المكاتب أن تتعطّل السيارة المتَّفق عليها
    فتُستبدل بأخرى، والعقد نفسه يبقى.
    """

    def __init__(self, contract, parent=None):
        super().__init__(
            parent,
            title="تعديل العقد %s" % contract["contract_number"],
            width=560,
        )
        self._contract = contract
        form = self.form

        self.vehicle = combo(
            [(row["id"], _vehicle_label(row)) for row in vehicles_repo.list_bookable()]
        )
        index = self.vehicle.findData(contract["vehicle_id"])
        if index < 0:
            # السيارة الحالية قد تكون في الصيانة فلا تظهر في القائمة: تُضاف يدوياً
            self.vehicle.addItem(
                "%s — %s" % (contract["vehicle_title"], contract["plate_number"]),
                contract["vehicle_id"],
            )
            index = self.vehicle.count() - 1
        self.vehicle.setCurrentIndex(index)
        self.vehicle.currentIndexChanged.connect(self._preview)

        self.start_date = date_field(
            QDate.fromString(contract["start_date"], "yyyy-MM-dd")
        )
        self.start_time = time_field(contract["start_time"] or "12:00")
        self.end_date = date_field(
            QDate.fromString(contract["expected_end_date"], "yyyy-MM-dd")
        )
        self.start_date.dateChanged.connect(self._preview)
        self.end_date.dateChanged.connect(self._preview)

        self.discount = money_field()
        self.discount.setValue(float(money.to_major(contract["discount"])))
        self.discount.valueChanged.connect(self._preview)

        self.extra = money_field()
        self.extra.setValue(float(money.to_major(contract["extra_charges"])))
        self.extra.valueChanged.connect(self._preview)

        self.pickup = QLineEdit(contract["pickup_location"] or "")
        self.notes = QPlainTextEdit(contract["notes"] or "")
        self.notes.setMaximumHeight(70)

        form.addRow("السيارة", self.vehicle)
        form.addRow("تاريخ الاستلام", self.start_date)
        form.addRow("وقت الاستلام", self.start_time)
        form.addRow("تاريخ التسليم المتوقَّع", self.end_date)
        form.addRow("خصم", self.discount)
        form.addRow("رسوم إضافية", self.extra)
        form.addRow("مكان الاستلام", self.pickup)
        form.addRow("ملاحظات", self.notes)
        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        card = Card(margins=(14, 12, 14, 12))
        card.body.addWidget(self.preview_label)
        self.add_widget(card)

        self.add_buttons(save_text="حفظ التعديل", on_save=self._save)

        self._preview()

    def _preview(self):
        vehicle = vehicles_repo.get(self.vehicle.currentData())
        if vehicle is None:
            return

        same_vehicle = vehicle["id"] == self._contract["vehicle_id"]
        daily = (self._contract["daily_rate_snapshot"] if same_vehicle
                 else vehicle["daily_rate"])
        weekly = (self._contract["weekly_rate_snapshot"] if same_vehicle
                  else vehicle["weekly_rate"])
        symbol = settings_repo.symbol_of(
            self._contract["currency_code"] if same_vehicle else vehicle["currency_code"]
        )

        try:
            estimate = pricing.quote(
                self.start_date.date().toString("yyyy-MM-dd"),
                self.end_date.date().toString("yyyy-MM-dd"),
                daily, weekly,
                money.to_minor(self.discount.value()),
                money.to_minor(self.extra.value()),
            )
        except ValueError as error:
            self.preview_label.setText("⚠ %s" % error)
            return

        paid = int(self._contract["paid_amount"])
        note = "" if same_vehicle else "\n⚠ تبديل السيارة يعتمد تعرفة السيارة الجديدة."

        self.preview_label.setText(
            "المدّة الجديدة: %d يوم (كانت %d)\n"
            "الإجمالي الجديد: %s (كان %s)\nالمدفوع: %s  |  المتبقّي: %s%s"
            % (
                estimate["days"], self._contract["days_count"],
                money.format_amount(estimate["total"], symbol),
                money.format_amount(self._contract["total_amount"], symbol),
                money.format_amount(paid, symbol),
                money.format_amount(estimate["total"] - paid, symbol),
                note,
            )
        )

    def _save(self):
        try:
            rental_service.update_contract(
                self._contract["id"],
                start_date=self.start_date.date().toString("yyyy-MM-dd"),
                expected_end_date=self.end_date.date().toString("yyyy-MM-dd"),
                start_time=self.start_time.time().toString("HH:mm"),
                vehicle_id=self.vehicle.currentData(),
                discount=money.to_minor(self.discount.value()),
                extra_charges=money.to_minor(self.extra.value()),
                pickup_location=self.pickup.text().strip() or None,
                notes=self.notes.toPlainText().strip() or None,
            )
        except Exception as error:
            show_error(self, error)
            return

        show_info(self, "حُفظ التعديل وأُعيد حساب قيمة العقد.")
        self.accept()


class PaymentDialog(FormDialog):
    """حوار تسجيل دفعة على عقد."""

    def __init__(self, contract, parent=None):
        super().__init__(
            parent,
            title="تسجيل دفعة — %s" % contract["contract_number"],
            width=440,
        )
        self._contract = contract

        symbol = settings_repo.symbol_of(contract["currency_code"])
        remaining = int(contract["balance_due"])

        info = QLabel(
            "إجمالي العقد: %s\nالمدفوع: %s\nالمتبقّي: %s"
            % (
                money.format_amount(contract["total_amount"], symbol),
                money.format_amount(contract["paid_amount"], symbol),
                money.format_amount(remaining, symbol),
            )
        )
        info.setWordWrap(True)
        self.body.insertWidget(0, info)

        form = self.form
        self.amount = money_field()
        self.amount.setMaximum(float(money.to_major(max(remaining, 0))))
        self.amount.setValue(float(money.to_major(max(remaining, 0))))

        self.method = combo(list(config.PAYMENT_METHOD_LABELS.items()))
        self.reference = QLineEdit()
        self.note = QLineEdit()

        form.addRow("المبلغ *", self.amount)
        form.addRow("طريقة الدفع", self.method)
        form.addRow("رقم المرجع / الإيصال", self.reference)
        form.addRow("ملاحظة", self.note)
        self.add_buttons(save_text="تسجيل الدفعة", on_save=self._save)

        if remaining <= 0:
            info.setText(info.text() + "\n\nالعقد مدفوع بالكامل.")
            self.save_button.setEnabled(False)

    def _save(self):
        try:
            payments_repo.add(
                self._contract["id"],
                money.to_minor(self.amount.value()),
                method=self.method.currentData(),
                reference=self.reference.text().strip() or None,
                note=self.note.text().strip() or None,
            )
        except Exception as error:
            show_error(self, error)
            return
        self.accept()


class ContractsPage(QWidget):
    """قائمة العقود مع كل إجراءاتها."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._read_only = False
        self._selected_contract = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = PageHeader("عقود الإيجار", "إنشاء العقود وإغلاقها وتحصيل المدفوعات")

        self.status_filter = combo(
            [("", "كل الحالات")] + list(config.CONTRACT_STATUS_LABELS.items())
        )
        self.status_filter.currentIndexChanged.connect(self.refresh)

        self.payment_filter = combo(
            [("", "كل حالات الدفع")] + list(config.PAYMENT_STATUS_LABELS.items())
        )
        self.payment_filter.currentIndexChanged.connect(self.refresh)

        self.search = search_box("بحث برقم العقد أو اسم العميل أو اللوحة…")
        self.search.textChanged.connect(self.refresh)

        header.actions.addWidget(self.status_filter)
        header.actions.addWidget(self.payment_filter)
        header.actions.addWidget(self.search)

        self.add_button = new_button = primary_button("+ عقد جديد")
        new_button.clicked.connect(self._new_contract)
        header.add_action(new_button)

        layout.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(12)

        table_card = Card()
        self.table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("plate_number", "اللوحة"),
                ("start_date", "البداية"),
                ("expected_end_date", "الانتهاء"),
                ("balance_due", "المتبقّي"),
                ("status", "الحالة"),
                ("payment_status", "الدفع"),
            ],
            stretch_column=1,
        )
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        table_card.body.addWidget(self.table)
        content.addWidget(table_card, 7)

        detail_card = Card()
        self.detail_title = QLabel("اختر عقداً لعرض تفاصيله")
        self.detail_title.setObjectName("sectionTitle")
        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.payments_table = DataTable(
            [("paid_at", "التاريخ"), ("amount", "المبلغ"), ("method", "الطريقة")],
            stretch_column=0,
        )
        self.payments_table.setMaximumHeight(180)

        actions = QVBoxLayout()
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()

        self.payment_button = primary_button("تسجيل دفعة")
        self.payment_button.clicked.connect(self._add_payment)
        self.close_button = QPushButton("إنهاء العقد")
        self.close_button.clicked.connect(self._close_contract)
        self.renew_button = QPushButton("تجديد")
        self.renew_button.setToolTip("إنشاء عقد جديد لنفس العميل والسيارة يبدأ من انتهاء هذا")
        self.renew_button.clicked.connect(self._renew)
        self.edit_button = QPushButton("تعديل")
        self.edit_button.setToolTip("تعديل تواريخ العقد أو سيارته أو خصمه")
        self.edit_button.clicked.connect(self._edit)
        self.extend_button = QPushButton("تمديد")
        self.extend_button.setToolTip("تمديد العقد نفسه بتاريخ انتهاء أبعد")
        self.extend_button.clicked.connect(self._extend)
        self.print_button = QPushButton("طباعة PDF")
        self.print_button.clicked.connect(self._print)
        self.cancel_button = QPushButton("إلغاء العقد")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self._cancel)

        for button in (self.payment_button, self.close_button, self.renew_button):
            row1.addWidget(button)
        for button in (self.edit_button, self.extend_button, self.print_button,
                       self.cancel_button):
            row2.addWidget(button)
        row2.addStretch(1)

        actions.addLayout(row1)
        actions.addLayout(row2)

        detail_card.body.addWidget(self.detail_title)
        detail_card.body.addWidget(self.detail_body)
        detail_card.body.addLayout(actions)
        detail_card.body.addWidget(QLabel("الدفعات المسجَّلة"))
        detail_card.body.addWidget(self.payments_table)
        # يدفع المحتوى إلى الأعلى فلا تتوزّع المساحة الفائضة بين العناصر
        detail_card.body.addStretch(1)

        content.addWidget(detail_card, 3)
        layout.addLayout(content, 1)

        self._set_actions_enabled(None)

    # ------------------------------------------------------------------
    def _set_actions_enabled(self, contract):
        self._selected_contract = contract
        # وضع القفل يمنع كل ما يغيّر العقود، وتبقى **الطباعة** وحدها متاحة:
        # العقد المطبوع حقٌّ لصاحبه لا امتياز اشتراك.
        editable = not self._read_only
        is_open = editable and bool(contract) and contract["status"] == "open"
        has_balance = bool(contract) and int(contract["balance_due"]) > 0

        self.payment_button.setEnabled(editable and bool(contract) and has_balance
                                       and contract["status"] != "cancelled")
        self.close_button.setEnabled(is_open)
        self.edit_button.setEnabled(is_open)
        self.extend_button.setEnabled(is_open)
        # التجديد متاح حتى بعد الإنهاء: العميل قد يعود بعد أيام فيُجدَّد له
        self.renew_button.setEnabled(
            editable and bool(contract) and contract["status"] != "cancelled"
        )
        self.print_button.setEnabled(bool(contract))
        self.cancel_button.setEnabled(
            editable and bool(contract) and contract["status"] != "cancelled"
            and session.has_role("admin")
        )

    def _refresh_action_state(self):
        self.add_button.setEnabled(not self._read_only)
        self._set_actions_enabled(self._selected_contract)

    # ------------------------------------------------------------------
    def set_read_only(self, read_only=True):
        """يعطّل أزرار التعديل ويُبقي العرض والطباعة — وضع القفل.

        الأزرار تُعطَّل ولا تُخفى: صاحب المكتب يرى ما كان يفعله ويعلم أن
        التجديد يعيده، ولا يظنّ أن المنظومة فقدت ما كانت تحسنه.
        """
        self._read_only = bool(read_only)
        self._refresh_action_state()


    def _selected(self):
        contract_id = self.table.selected_id()
        return contracts_repo.get(contract_id) if contract_id else None

    def _format(self, row, key):
        symbol = settings_repo.symbol_of(row["currency_code"]) if "currency_code" in row.keys() else ""
        if key in ("total_amount", "balance_due", "amount", "paid_amount"):
            return money.format_amount(row[key], symbol)
        if key == "status":
            return config.CONTRACT_STATUS_LABELS.get(row["status"], row["status"])
        if key == "payment_status":
            return config.PAYMENT_STATUS_LABELS.get(row["payment_status"], "")
        if key == "method":
            return config.PAYMENT_METHOD_LABELS.get(row["method"], row["method"])
        if key == "paid_at":
            return str(row["paid_at"])[:16]
        return row[key] if key in row.keys() else ""

    def _payment_format(self, row, key):
        if key == "amount":
            contract = self._selected()
            symbol = settings_repo.symbol_of(contract["currency_code"]) if contract else ""
            return money.format_amount(row["amount"], symbol)
        return self._format(row, key)

    def _on_select(self):
        contract = self._selected()
        if contract is None:
            self.detail_title.setText("اختر عقداً لعرض تفاصيله")
            self.detail_body.setText("")
            self.payments_table.fill([])
            self._set_actions_enabled(None)
            return

        symbol = settings_repo.symbol_of(contract["currency_code"])
        overdue = ""
        if contract["status"] == "open":
            expected = datetime.date.fromisoformat(contract["expected_end_date"])
            late = (datetime.date.today() - expected).days
            if late > 0:
                overdue = "\n⚠ متأخّر عن موعد التسليم بـ %d يوم" % late

        # العقد المُغلق بالاحتساب الساعي تُعرض مدّته بالساعات لا بالأيام
        if ("billing_mode" in contract.keys() and contract["billing_mode"] == "hourly"
                and contract["hours_count"]):
            duration = "%s — %d ساعة" % (
                pricing.describe_duration(contract["hours_count"]),
                contract["hours_count"],
            )
        else:
            duration = "%d يوم" % contract["days_count"]

        self.detail_title.setText("العقد %s" % contract["contract_number"])
        self.detail_body.setText(fix_dates(
            "العميل: %s (%s)\nالسيارة: %s — %s\n"
            "المدّة: %s ← %s (%s)\n"
            "الإجمالي: %s  |  المدفوع: %s  |  المتبقّي: %s\n"
            "الحالة: %s  |  الدفع: %s\nأنشأه: %s%s"
            % (
                contract["customer_name"], contract["customer_phone"],
                contract["vehicle_title"], contract["plate_number"],
                contract["start_date"],
                contract["actual_end_date"] or contract["expected_end_date"],
                duration,
                money.format_amount(contract["total_amount"], symbol),
                money.format_amount(contract["paid_amount"], symbol),
                money.format_amount(contract["balance_due"], symbol),
                config.CONTRACT_STATUS_LABELS.get(contract["status"], ""),
                config.PAYMENT_STATUS_LABELS.get(contract["payment_status"], ""),
                contract["created_by_name"] or "—",
                overdue,
            )
        ))

        self.payments_table.fill(
            payments_repo.of_contract(contract["id"]), self._payment_format
        )
        self._set_actions_enabled(contract)

    # ------------------------------------------------------------------
    def _new_contract(self):
        dialog = NewContractDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            if dialog.created_id and confirm(self, "هل تريد طباعة العقد الآن؟"):
                self._print(dialog.created_id)

    def _add_payment(self):
        contract = self._selected()
        if contract is None:
            return
        if PaymentDialog(contract, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _close_contract(self):
        contract = self._selected()
        if contract is None:
            return
        if CloseContractDialog(contract, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit(self):
        contract = self._selected()
        if contract is None:
            return
        if EditContractDialog(contract, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _renew(self):
        """يفتح حوار عقد جديد مهيّأً بنفس العميل والسيارة، يبدأ من انتهاء الحالي."""
        contract = self._selected()
        if contract is None:
            return

        preset = {
            "customer_id": contract["customer_id"],
            "vehicle_id": contract["vehicle_id"],
            "start_date": contract["actual_end_date"] or contract["expected_end_date"],
            "start_time": contract["start_time"],
            "days": 7,
            "notes": "تجديد للعقد %s" % contract["contract_number"],
        }

        dialog = NewContractDialog(self, preset=preset)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _extend(self):
        contract = self._selected()
        if contract is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("تمديد العقد %s" % contract["contract_number"])
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        new_date = date_field(
            QDate.fromString(contract["expected_end_date"], "yyyy-MM-dd").addDays(1)
        )
        form.addRow("تاريخ الانتهاء الجديد", new_date)
        buttons = QHBoxLayout()
        save = primary_button("تمديد")
        save.clicked.connect(dialog.accept)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(dialog.reject)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            estimate = rental_service.extend_contract(
                contract["id"], new_date.date().toString("yyyy-MM-dd")
            )
        except Exception as error:
            show_error(self, error)
            return

        symbol = settings_repo.symbol_of(contract["currency_code"])
        show_info(
            self,
            "تم التمديد. المدّة الجديدة %d يوم، والإجمالي %s."
            % (estimate["days"], money.format_amount(estimate["total"], symbol)),
        )
        self.refresh()

    def _print(self, contract_id=None):
        contract_id = contract_id or self.table.selected_id()
        if not contract_id:
            return
        try:
            path = contract_pdf.export_pdf(contract_id)
        except Exception as error:
            show_error(self, "تعذّر توليد ملف العقد: %s" % error)
            return
        show_info(self, "حُفظ العقد بصيغة PDF في:\n%s" % path)

    def _cancel(self):
        contract = self._selected()
        if contract is None:
            return
        if not confirm(
            self,
            "إلغاء العقد %s سيحرّر السيارة ويُبقي سجلّ العقد ودفعاته. هل تريد المتابعة؟"
            % contract["contract_number"],
        ):
            return

        try:
            rental_service.cancel_contract(contract["id"], reason="إلغاء يدوي")
        except Exception as error:
            show_error(self, error)
            return

        show_info(self, "تم إلغاء العقد.")
        self.refresh()

    def refresh(self):
        try:
            rows = contracts_repo.search(
                term=self.search.text(),
                status=self.status_filter.currentData() or None,
                payment_status=self.payment_filter.currentData() or None,
            )
            self.table.fill(rows, self._format)
            self._on_select()
        except Exception as error:
            show_error(self, error)

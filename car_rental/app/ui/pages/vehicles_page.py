# -*- coding: utf-8 -*-
"""صفحة السيارات: الأسطول وحالاته وتعرفة الإيجار."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ... import config
from ...core import money, session
from ...repositories import settings_repo, vehicles_repo
from ...services import pricing
from ..widgets.common import (
    Card, DataTable, PageHeader, combo, confirm, fix_dates, money_field,
    primary_button, search_box, show_error, show_info,
)


class VehicleDialog(QDialog):
    """حوار إضافة سيارة أو تعديل بياناتها وتعرفتها."""

    def __init__(self, parent=None, vehicle=None):
        super().__init__(parent)
        self._vehicle = vehicle

        self.setWindowTitle("تعديل بيانات سيارة" if vehicle else "إضافة سيارة جديدة")
        self.setMinimumWidth(520)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.brand = QLineEdit()
        self.model = QLineEdit()

        self.year = QSpinBox()
        self.year.setRange(1950, 2100)
        self.year.setValue(2020)

        self.plate_number = QLineEdit()
        self.color = QLineEdit()
        self.daily_rate = money_field()
        self.weekly_rate = money_field()
        self.hourly_rate = money_field()
        self.currency = combo(
            [(row["code"], "%s (%s)" % (row["name_ar"], row["symbol"]))
             for row in settings_repo.list_currencies()]
        )

        self.odometer = QSpinBox()
        self.odometer.setRange(0, 5_000_000)
        self.odometer.setSuffix(" كم")

        self.chassis = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)

        form.addRow("الماركة *", self.brand)
        form.addRow("الموديل *", self.model)
        form.addRow("سنة الصنع *", self.year)
        form.addRow("رقم اللوحة *", self.plate_number)
        form.addRow("اللون *", self.color)
        form.addRow("السعر اليومي *", self.daily_rate)
        form.addRow("السعر الأسبوعي (اتركه صفراً إن لم يوجد)", self.weekly_rate)
        form.addRow("سعر الساعة (اتركه صفراً للاحتساب التلقائي)", self.hourly_rate)
        form.addRow("العملة", self.currency)
        form.addRow("قراءة العدّاد", self.odometer)
        form.addRow("رقم الشاصي", self.chassis)
        form.addRow("ملاحظات", self.notes)

        layout.addLayout(form)

        hint = QLabel(
            "السعر الأسبوعي يُطبَّق تلقائياً على كل أسبوع كامل من مدّة العقد،"
            " ولن يدفع العميل عن أيام متبقّية أكثر من ثمن أسبوع كامل.\n"
            "وسعر الساعة يُستعمل عند الإرجاع المبكّر؛ إن تُرك صفراً حُسب تلقائياً"
            " بقسمة السعر اليومي على 24."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        save = primary_button("حفظ")
        save.clicked.connect(self._save)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if vehicle:
            self._load(vehicle)

    def _load(self, row):
        self.brand.setText(row["brand"] or "")
        self.model.setText(row["model"] or "")
        self.year.setValue(int(row["year"] or 2020))
        self.plate_number.setText(row["plate_number"] or "")
        self.color.setText(row["color"] or "")
        self.daily_rate.setValue(float(money.to_major(row["daily_rate"])))
        self.weekly_rate.setValue(float(money.to_major(row["weekly_rate"])))
        self.hourly_rate.setValue(float(money.to_major(row["hourly_rate"])))
        self.odometer.setValue(int(row["odometer"] or 0))
        self.chassis.setText(row["chassis_number"] or "")
        self.notes.setPlainText(row["notes"] or "")

        index = self.currency.findData(row["currency_code"])
        if index >= 0:
            self.currency.setCurrentIndex(index)

    def data(self):
        return {
            "brand": self.brand.text().strip(),
            "model": self.model.text().strip(),
            "year": self.year.value(),
            "plate_number": self.plate_number.text().strip(),
            "color": self.color.text().strip(),
            "daily_rate": money.to_minor(self.daily_rate.value()),
            "weekly_rate": money.to_minor(self.weekly_rate.value()),
            "hourly_rate": money.to_minor(self.hourly_rate.value()),
            "currency_code": self.currency.currentData(),
            "odometer": self.odometer.value(),
            "chassis_number": self.chassis.text().strip() or None,
            "notes": self.notes.toPlainText().strip() or None,
        }

    def _save(self):
        try:
            if self._vehicle:
                vehicles_repo.update(self._vehicle["id"], self.data())
            else:
                vehicles_repo.create(self.data())
        except Exception as error:
            show_error(self, error)
            return
        self.accept()


class VehiclesPage(QWidget):
    """أسطول السيارات مع ترشيح بالحالة."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = PageHeader("السيارات", "الأسطول وحالة كل سيارة وتعرفة إيجارها")

        self.status_filter = combo(
            [("", "كل الحالات")]
            + [(key, label) for key, label in config.VEHICLE_STATUS_LABELS.items()]
        )
        self.status_filter.currentIndexChanged.connect(self.refresh)

        self.search = search_box("بحث برقم اللوحة أو الماركة…")
        self.search.textChanged.connect(self.refresh)

        header.actions.addWidget(self.status_filter)
        header.actions.addWidget(self.search)

        add_button = primary_button("+ سيارة جديدة")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)

        layout.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(12)

        table_card = Card()
        self.table = DataTable(
            [
                ("vehicle_title", "السيارة"),
                ("plate_number", "رقم اللوحة"),
                ("year", "سنة الصنع"),
                ("color", "اللون"),
                ("daily_rate", "السعر اليومي"),
                ("weekly_rate", "السعر الأسبوعي"),
                ("status", "الحالة"),
            ],
            stretch_column=0,
        )
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.doubleClicked.connect(self._edit)
        table_card.body.addWidget(self.table)
        content.addWidget(table_card, 3)

        detail_card = Card()
        self.detail_title = QLabel("اختر سيارة لعرض تفاصيلها")
        self.detail_title.setObjectName("sectionTitle")
        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.history_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("start_date", "البداية"),
                ("actual_end_date", "الإرجاع"),
            ],
            stretch_column=1,
        )

        buttons = QHBoxLayout()
        self.edit_button = QPushButton("تعديل")
        self.edit_button.clicked.connect(self._edit)
        self.maintenance_button = QPushButton("نقل إلى الصيانة")
        self.maintenance_button.clicked.connect(lambda: self._set_status("maintenance"))
        self.available_button = QPushButton("إتاحة")
        self.available_button.clicked.connect(lambda: self._set_status("available"))
        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("danger")
        self.delete_button.clicked.connect(self._delete)

        for button in (self.edit_button, self.maintenance_button,
                       self.available_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        detail_card.body.addWidget(self.detail_title)
        detail_card.body.addWidget(self.detail_body)
        detail_card.body.addLayout(buttons)
        self.reservations_label = QLabel("الحجوزات القادمة")
        self.reservations_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("start_date", "من"),
                ("expected_end_date", "إلى"),
            ],
            stretch_column=1,
        )
        self.reservations_table.setMaximumHeight(140)

        detail_card.body.addWidget(self.reservations_label)
        detail_card.body.addWidget(self.reservations_table)
        detail_card.body.addWidget(QLabel("سجلّ عقود السيارة"))
        detail_card.body.addWidget(self.history_table)
        detail_card.body.addStretch(1)

        content.addWidget(detail_card, 2)
        layout.addLayout(content, 1)

        self._set_detail_enabled(False)

    # ------------------------------------------------------------------
    def _set_detail_enabled(self, enabled, status=None):
        self.edit_button.setEnabled(enabled)
        self.maintenance_button.setEnabled(enabled and status == "available")
        self.available_button.setEnabled(enabled and status == "maintenance")
        self.delete_button.setEnabled(enabled and session.has_role("admin"))

    def _selected(self):
        vehicle_id = self.table.selected_id()
        return vehicles_repo.get(vehicle_id) if vehicle_id else None

    def _format(self, row, key):
        if key == "vehicle_title":
            return "%s %s" % (row["brand"], row["model"])
        if key in ("daily_rate", "weekly_rate"):
            symbol = settings_repo.symbol_of(row["currency_code"])
            if key == "weekly_rate" and not row["weekly_rate"]:
                return "—"
            return money.format_amount(row[key], symbol)
        if key == "status":
            return config.VEHICLE_STATUS_LABELS.get(row["status"], row["status"])
        return row[key] if key in row.keys() else ""

    def _on_select(self):
        vehicle = self._selected()
        if vehicle is None:
            self.detail_title.setText("اختر سيارة لعرض تفاصيلها")
            self.detail_body.setText("")
            self.history_table.fill([])
            self.reservations_table.fill([])
            self._set_detail_enabled(False)
            return

        symbol = settings_repo.symbol_of(vehicle["currency_code"])
        self.detail_title.setText(
            "%s %s — %s" % (vehicle["brand"], vehicle["model"], vehicle["plate_number"])
        )
        self.detail_body.setText(fix_dates(
            "الحالة: %s\nسنة الصنع: %s\nاللون: %s\nالعدّاد: %s كم\n"
            "السعر اليومي: %s\nالسعر الأسبوعي: %s\nسعر الساعة: %s\n"
            "رقم الشاصي: %s\nملاحظات: %s"
            % (
                config.VEHICLE_STATUS_LABELS.get(vehicle["status"], ""),
                vehicle["year"],
                vehicle["color"],
                "{:,}".format(vehicle["odometer"] or 0),
                money.format_amount(vehicle["daily_rate"], symbol),
                money.format_amount(vehicle["weekly_rate"], symbol)
                if vehicle["weekly_rate"] else "—",
                money.format_amount(
                    int(vehicle["hourly_rate"] or 0)
                    or pricing.default_hourly_rate(vehicle["daily_rate"]), symbol
                ) + ("" if vehicle["hourly_rate"] else " (تلقائي)"),
                vehicle["chassis_number"] or "—",
                vehicle["notes"] or "—",
            )
        ))

        reservations = vehicles_repo.upcoming_reservations(vehicle["id"])
        self.reservations_table.fill(reservations)
        self.reservations_label.setText(
            "الحجوزات القادمة (%d)" % len(reservations) if reservations
            else "الحجوزات القادمة — لا يوجد"
        )

        self.history_table.fill(vehicles_repo.history(vehicle["id"]))
        self._set_detail_enabled(True, vehicle["status"])

    # ------------------------------------------------------------------
    def _add(self):
        if VehicleDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit(self):
        vehicle = self._selected()
        if vehicle is None:
            return
        if VehicleDialog(self, vehicle).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _set_status(self, status):
        vehicle = self._selected()
        if vehicle is None:
            return
        try:
            vehicles_repo.set_status(vehicle["id"], status)
        except Exception as error:
            show_error(self, error)
            return
        self.refresh()

    def _delete(self):
        vehicle = self._selected()
        if vehicle is None:
            return
        if not confirm(self, "هل تريد حذف السيارة «%s» نهائياً؟" % vehicle["plate_number"]):
            return
        try:
            vehicles_repo.delete(vehicle["id"])
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "تم حذف السيارة.")
        self.refresh()

    def refresh(self):
        try:
            rows = vehicles_repo.search(
                term=self.search.text(), status=self.status_filter.currentData() or None
            )
            self.table.fill(rows, self._format)
        except Exception as error:
            show_error(self, error)

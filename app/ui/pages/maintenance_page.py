# -*- coding: utf-8 -*-
"""صفحة الصيانة والمخالفات المرورية (تبويبان في شاشة واحدة)."""

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ... import config
from ...core import money
from ...repositories import maintenance_repo, settings_repo, vehicles_repo
from ..widgets.common import (
    Card, DataTable, FormDialog, PageHeader, combo, confirm, date_field,
    money_field, primary_button, show_error, show_info,
)


def _vehicle_items(only_free=False):
    rows = vehicles_repo.search(limit=2000)
    return [
        (row["id"], "%s %s — %s" % (row["brand"], row["model"], row["plate_number"]))
        for row in rows
        if not only_free or row["status"] != "rented"
    ]


def _currency_items():
    return [(row["code"], "%s (%s)" % (row["name_ar"], row["symbol"]))
            for row in settings_repo.list_currencies()]


class MaintenanceDialog(FormDialog):
    """حوار فتح سجلّ صيانة جديد."""
    def __init__(self, parent=None):
        super().__init__(parent, title="إدخال سيارة إلى الصيانة", width=480)

        form = self.form

        self.vehicle = combo(_vehicle_items(only_free=True))
        self.kind = combo(list(config.MAINTENANCE_KIND_LABELS.items()))
        self.cost = money_field()
        self.currency = combo(_currency_items())
        self.workshop = QLineEdit()

        self.odometer = QSpinBox()
        self.odometer.setRange(0, 5_000_000)
        self.odometer.setSuffix(" كم")

        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(90)

        form.addRow("السيارة *", self.vehicle)
        form.addRow("نوع الصيانة", self.kind)
        form.addRow("التكلفة المتوقَّعة", self.cost)
        form.addRow("العملة", self.currency)
        form.addRow("الورشة", self.workshop)
        form.addRow("قراءة العدّاد", self.odometer)
        form.addRow("الوصف *", self.description)
        self.add_buttons(save_text="حفظ", on_save=self._save)

    def _save(self):
        if self.vehicle.currentData() is None:
            show_error(self, "اختر السيارة.")
            return
        try:
            maintenance_repo.open_maintenance(
                self.vehicle.currentData(),
                self.description.toPlainText().strip(),
                kind=self.kind.currentData(),
                cost=money.to_minor(self.cost.value()),
                currency_code=self.currency.currentData(),
                workshop=self.workshop.text().strip() or None,
                odometer=self.odometer.value() or None,
            )
        except Exception as error:
            show_error(self, error)
            return
        self.accept()


class ViolationDialog(FormDialog):
    """حوار تسجيل مخالفة مرورية."""
    def __init__(self, parent=None):
        super().__init__(parent, title="تسجيل مخالفة مرورية", width=480)

        form = self.form

        self.vehicle = combo(_vehicle_items())
        self.occurred_at = date_field()
        self.amount = money_field()
        self.currency = combo(_currency_items())
        self.reference = QLineEdit()
        self.charged = QCheckBox("تُحمَّل على العميل المستأجر")
        self.charged.setChecked(True)
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(80)

        form.addRow("السيارة *", self.vehicle)
        form.addRow("تاريخ المخالفة *", self.occurred_at)
        form.addRow("قيمة المخالفة", self.amount)
        form.addRow("العملة", self.currency)
        form.addRow("رقم المخالفة", self.reference)
        form.addRow("", self.charged)
        form.addRow("الوصف *", self.description)
        hint = QLabel(
            "إن كانت السيارة ضمن عقد في تاريخ المخالفة، تُربط المخالفة بذلك العقد تلقائياً."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.add_buttons(save_text="حفظ", on_save=self._save)

    def _save(self):
        if self.vehicle.currentData() is None:
            show_error(self, "اختر السيارة.")
            return
        try:
            maintenance_repo.add_violation(
                self.vehicle.currentData(),
                self.occurred_at.date().toString("yyyy-MM-dd"),
                self.description.toPlainText().strip(),
                amount=money.to_minor(self.amount.value()),
                currency_code=self.currency.currentData(),
                reference=self.reference.text().strip() or None,
                is_charged_to_customer=1 if self.charged.isChecked() else 0,
            )
        except Exception as error:
            show_error(self, error)
            return
        self.accept()


class MaintenancePage(QWidget):
    """تبويبا الصيانة والمخالفات."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = PageHeader("الصيانة والمخالفات", "متابعة صيانة الأسطول والمخالفات المرورية")

        maintenance_button = primary_button("+ إدخال صيانة")
        maintenance_button.clicked.connect(self._add_maintenance)
        violation_button = QPushButton("+ تسجيل مخالفة")
        violation_button.clicked.connect(self._add_violation)
        header.add_action(maintenance_button)
        header.add_action(violation_button)

        layout.addWidget(header)

        tabs = QTabWidget()

        # --- تبويب الصيانة ---
        maintenance_tab = QWidget()
        maintenance_layout = QVBoxLayout(maintenance_tab)
        maintenance_layout.setContentsMargins(12, 12, 12, 12)

        controls = QHBoxLayout()
        self.only_open = QCheckBox("السجلّات المفتوحة فقط")
        self.only_open.stateChanged.connect(self.refresh)
        self.finish_button = QPushButton("إنهاء الصيانة المختارة")
        self.finish_button.clicked.connect(self._finish_maintenance)
        controls.addWidget(self.only_open)
        controls.addStretch(1)
        controls.addWidget(self.finish_button)

        self.maintenance_table = DataTable(
            [
                ("vehicle_title", "السيارة"),
                ("plate_number", "اللوحة"),
                ("kind", "النوع"),
                ("started_at", "تاريخ الدخول"),
                ("finished_at", "تاريخ الخروج"),
                ("cost", "التكلفة"),
                ("workshop", "الورشة"),
                ("description", "الوصف"),
            ],
            stretch_column=7,
        )

        maintenance_layout.addLayout(controls)
        maintenance_layout.addWidget(self.maintenance_table)
        tabs.addTab(maintenance_tab, "سجلّ الصيانة")

        # --- تبويب المخالفات ---
        violations_tab = QWidget()
        violations_layout = QVBoxLayout(violations_tab)
        violations_layout.setContentsMargins(12, 12, 12, 12)

        violation_controls = QHBoxLayout()
        self.only_unsettled = QCheckBox("غير المسدَّدة فقط")
        self.only_unsettled.stateChanged.connect(self.refresh)
        self.settle_button = QPushButton("تحديد المخالفة كمسدَّدة")
        self.settle_button.clicked.connect(self._settle)
        violation_controls.addWidget(self.only_unsettled)
        violation_controls.addStretch(1)
        violation_controls.addWidget(self.settle_button)

        self.violations_table = DataTable(
            [
                ("plate_number", "اللوحة"),
                ("occurred_at", "التاريخ"),
                ("amount", "القيمة"),
                ("contract_number", "العقد"),
                ("customer_name", "العميل"),
                ("is_settled", "الحالة"),
                ("description", "الوصف"),
            ],
            stretch_column=6,
        )

        violations_layout.addLayout(violation_controls)
        violations_layout.addWidget(self.violations_table)
        tabs.addTab(violations_tab, "المخالفات المرورية")

        card = Card(margins=(6, 6, 6, 6))
        card.body.addWidget(tabs)
        layout.addWidget(card, 1)

    # ------------------------------------------------------------------
    def _format_maintenance(self, row, key):
        if key == "kind":
            return config.MAINTENANCE_KIND_LABELS.get(row["kind"], row["kind"])
        if key == "cost":
            return money.format_amount(row["cost"], settings_repo.symbol_of(row["currency_code"]))
        if key in ("started_at", "finished_at"):
            value = row[key]
            return str(value)[:16] if value else "— مفتوح —"
        return row[key] if key in row.keys() else ""

    def _format_violation(self, row, key):
        if key == "amount":
            return money.format_amount(row["amount"], settings_repo.symbol_of(row["currency_code"]))
        if key == "is_settled":
            return "مسدَّدة" if row["is_settled"] else "غير مسدَّدة"
        if key in ("contract_number", "customer_name"):
            return row[key] or "—"
        return row[key] if key in row.keys() else ""

    def _add_maintenance(self):
        if MaintenanceDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _add_violation(self):
        if ViolationDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _finish_maintenance(self):
        record_id = self.maintenance_table.selected_id()
        if not record_id:
            show_error(self, "اختر سجلّ صيانة أولاً.")
            return
        if not confirm(self, "إنهاء الصيانة سيعيد السيارة إلى حالة «متاحة». متابعة؟"):
            return
        try:
            maintenance_repo.close_maintenance(record_id)
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "أُنهيت الصيانة وأصبحت السيارة متاحة.")
        self.refresh()

    def _settle(self):
        violation_id = self.violations_table.selected_id()
        if not violation_id:
            show_error(self, "اختر مخالفة أولاً.")
            return
        try:
            maintenance_repo.settle_violation(violation_id)
        except Exception as error:
            show_error(self, error)
            return
        self.refresh()

    def refresh(self):
        try:
            self.maintenance_table.fill(
                maintenance_repo.list_maintenance(only_open=self.only_open.isChecked()),
                self._format_maintenance,
            )
            self.violations_table.fill(
                maintenance_repo.list_violations(only_unsettled=self.only_unsettled.isChecked()),
                self._format_violation,
            )
        except Exception as error:
            show_error(self, error)

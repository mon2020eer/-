# -*- coding: utf-8 -*-
"""صفحة الإعدادات: بيانات المكتب، والعملات وأسعار الصرف، وخيارات النسخ."""

from PyQt6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ... import config
from ...core import money
from ...repositories import settings_repo
from ..widgets.common import (
    Card, DataTable, PageHeader, combo, money_field, primary_button, show_error,
    show_info,
)


class SettingsPage(QWidget):
    """إعدادات المنظومة — للمدير فقط."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        layout.addWidget(PageHeader("الإعدادات", "بيانات المكتب والعملات وخيارات النسخ الاحتياطي"))

        body = QHBoxLayout()
        body.setSpacing(12)

        # --- بيانات المكتب ---
        office_card = Card()
        office_title = QLabel("بيانات المكتب (تظهر في ترويسة العقد المطبوع)")
        office_title.setObjectName("sectionTitle")

        office_form = QFormLayout()
        office_form.setSpacing(10)

        self.office_name = QLineEdit()
        self.office_phone = QLineEdit()
        self.office_address = QLineEdit()

        office_form.addRow("اسم المكتب", self.office_name)
        office_form.addRow("رقم الهاتف", self.office_phone)
        office_form.addRow("العنوان", self.office_address)

        backup_title = QLabel("النسخ الاحتياطي")
        backup_title.setObjectName("sectionTitle")

        backup_form = QFormLayout()
        backup_form.setSpacing(10)

        self.backup_enabled = QCheckBox("تفعيل النسخ الاحتياطي")
        self.auto_daily = QCheckBox("نسخة تلقائية يومية عند تشغيل البرنامج")

        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setSuffix(" نسخة")

        backup_form.addRow("", self.backup_enabled)
        backup_form.addRow("", self.auto_daily)
        backup_form.addRow("عدد النسخ المحفوظة في Drive", self.retention)

        save_button = primary_button("حفظ الإعدادات")
        save_button.clicked.connect(self._save)

        office_card.body.addWidget(office_title)
        office_card.body.addLayout(office_form)
        office_card.body.addSpacing(10)
        office_card.body.addWidget(backup_title)
        office_card.body.addLayout(backup_form)
        office_card.body.addSpacing(6)
        office_card.body.addWidget(save_button)
        office_card.body.addStretch(1)

        body.addWidget(office_card, 1)

        # --- العملات ---
        currency_card = Card()
        currency_title = QLabel("العملات وأسعار الصرف")
        currency_title.setObjectName("sectionTitle")

        currency_hint = QLabel(
            "سعر الصرف يُستخدم لتجميع التقارير بالعملة الأساس فقط.\n"
            "العقود السابقة تحتفظ بسعر الصرف وقت إنشائها ولا تتأثّر بأي تعديل هنا."
        )
        currency_hint.setObjectName("hint")
        currency_hint.setWordWrap(True)

        self.currency_table = DataTable(
            [
                ("name_ar", "العملة"),
                ("code", "الرمز"),
                ("symbol", "العلامة"),
                ("rate_to_base", "سعر الصرف"),
                ("is_base", "الأساس"),
                ("updated_at", "آخر تحديث"),
            ],
            stretch_column=0,
        )

        rate_row = QHBoxLayout()
        self.currency_select = combo([])
        self.rate_value = money_field(maximum=100000.0)
        self.rate_value.setDecimals(4)
        update_rate = QPushButton("تحديث سعر الصرف")
        update_rate.clicked.connect(self._update_rate)

        rate_row.addWidget(QLabel("العملة"))
        rate_row.addWidget(self.currency_select)
        rate_row.addWidget(QLabel("السعر مقابل العملة الأساس"))
        rate_row.addWidget(self.rate_value)
        rate_row.addWidget(update_rate)
        rate_row.addStretch(1)

        base_row = QHBoxLayout()
        self.base_select = combo([])
        set_base = QPushButton("جعلها العملة الأساس")
        set_base.clicked.connect(self._set_base)
        base_row.addWidget(QLabel("العملة الأساس"))
        base_row.addWidget(self.base_select)
        base_row.addWidget(set_base)
        base_row.addStretch(1)

        currency_card.body.addWidget(currency_title)
        currency_card.body.addWidget(currency_hint)
        currency_card.body.addWidget(self.currency_table)
        currency_card.body.addLayout(rate_row)
        currency_card.body.addLayout(base_row)

        info = QLabel("مجلد بيانات التطبيق: %s" % config.DATA_DIR)
        info.setObjectName("hint")
        info.setWordWrap(True)
        currency_card.body.addWidget(info)

        body.addWidget(currency_card, 1)
        layout.addLayout(body, 1)

    # ------------------------------------------------------------------
    def _format_currency(self, row, key):
        if key == "rate_to_base":
            return str(money.rate_to_display(row["rate_to_base"]))
        if key == "is_base":
            return "نعم" if row["is_base"] else ""
        if key == "updated_at":
            return str(row["updated_at"])[:16]
        return row[key] if key in row.keys() else ""

    def _save(self):
        try:
            settings_repo.set_many({
                "office_name": self.office_name.text().strip(),
                "office_phone": self.office_phone.text().strip(),
                "office_address": self.office_address.text().strip(),
                "backup_enabled": "1" if self.backup_enabled.isChecked() else "0",
                "auto_backup_daily": "1" if self.auto_daily.isChecked() else "0",
                "backup_retention": str(self.retention.value()),
            })
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "حُفظت الإعدادات.")

    def _update_rate(self):
        code = self.currency_select.currentData()
        if not code:
            return
        try:
            settings_repo.set_exchange_rate(code, self.rate_value.value())
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "حُدِّث سعر الصرف.")
        self.refresh()

    def _set_base(self):
        code = self.base_select.currentData()
        if not code:
            return
        try:
            settings_repo.set_base_currency(code)
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "تم تغيير العملة الأساس وإعادة نسبة أسعار الصرف إليها.")
        self.refresh()

    def refresh(self):
        try:
            values = settings_repo.all_settings()
            self.office_name.setText(values.get("office_name", ""))
            self.office_phone.setText(values.get("office_phone", ""))
            self.office_address.setText(values.get("office_address", ""))
            self.backup_enabled.setChecked(values.get("backup_enabled", "1") == "1")
            self.auto_daily.setChecked(values.get("auto_backup_daily", "1") == "1")
            self.retention.setValue(int(values.get("backup_retention") or 30))

            currencies = settings_repo.list_currencies()
            self.currency_table.fill(currencies, self._format_currency)

            self.currency_select.clear()
            self.base_select.clear()
            for row in currencies:
                label = "%s (%s)" % (row["name_ar"], row["code"])
                self.base_select.addItem(label, row["code"])
                if not row["is_base"]:
                    self.currency_select.addItem(label, row["code"])
        except Exception as error:
            show_error(self, error)

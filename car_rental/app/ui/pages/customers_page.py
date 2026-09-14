# -*- coding: utf-8 -*-
"""صفحة العملاء: القائمة والبحث والإضافة والتعديل والمرفقات."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ...core import money, session
from ...repositories import customers_repo, settings_repo
from ..widgets.common import (
    Card, DataTable, PageHeader, confirm, date_field, fix_dates, primary_button,
    search_box, show_error, show_info,
)


class CustomerDialog(QDialog):
    """حوار إضافة عميل أو تعديل بياناته."""

    def __init__(self, parent=None, customer=None):
        super().__init__(parent)
        self._customer = customer

        self.setWindowTitle("تعديل بيانات عميل" if customer else "إضافة عميل جديد")
        self.setMinimumWidth(520)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.full_name = QLineEdit()
        self.phone = QLineEdit()
        self.national_id = QLineEdit()
        self.license_number = QLineEdit()
        self.license_expiry = date_field()
        self.nationality = QLineEdit()
        self.address = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(80)
        self.blacklisted = QCheckBox("إدراج العميل في القائمة السوداء (يمنع التعاقد معه)")

        form.addRow("الاسم الكامل *", self.full_name)
        form.addRow("رقم الهاتف *", self.phone)
        form.addRow("رقم الجواز / الرقم الوطني *", self.national_id)
        form.addRow("رقم رخصة القيادة *", self.license_number)
        form.addRow("تاريخ انتهاء الرخصة", self.license_expiry)
        form.addRow("الجنسية", self.nationality)
        form.addRow("العنوان", self.address)
        form.addRow("ملاحظات", self.notes)
        form.addRow("", self.blacklisted)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = primary_button("حفظ")
        save.clicked.connect(self._save)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if customer:
            self._load(customer)

    def _load(self, row):
        self.full_name.setText(row["full_name"] or "")
        self.phone.setText(row["phone"] or "")
        self.national_id.setText(row["national_id"] or "")
        self.license_number.setText(row["license_number"] or "")
        self.nationality.setText(row["nationality"] or "")
        self.address.setText(row["address"] or "")
        self.notes.setPlainText(row["notes"] or "")
        self.blacklisted.setChecked(bool(row["is_blacklisted"]))
        if row["license_expiry"]:
            from PyQt6.QtCore import QDate

            self.license_expiry.setDate(QDate.fromString(row["license_expiry"], "yyyy-MM-dd"))

    def data(self):
        return {
            "full_name": self.full_name.text().strip(),
            "phone": self.phone.text().strip(),
            "national_id": self.national_id.text().strip(),
            "license_number": self.license_number.text().strip(),
            "license_expiry": self.license_expiry.date().toString("yyyy-MM-dd"),
            "nationality": self.nationality.text().strip() or None,
            "address": self.address.text().strip() or None,
            "notes": self.notes.toPlainText().strip() or None,
            "is_blacklisted": 1 if self.blacklisted.isChecked() else 0,
        }

    def _save(self):
        try:
            if self._customer:
                customers_repo.update(self._customer["id"], self.data())
            else:
                customers_repo.create(self.data())
        except Exception as error:
            show_error(self, error)
            return
        self.accept()


class CustomersPage(QWidget):
    """قائمة العملاء مع تفاصيل العميل المختار."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = PageHeader("العملاء", "إدارة بيانات المستأجرين ووثائقهم")

        # العملاء الذين يترددون على المكتب كثيراً أهمّ من الترتيب الأبجدي
        self.frequent_toggle = QCheckBox("الأكثر تعاملاً أولاً")
        self.frequent_toggle.setToolTip(
            "ترتيب العملاء بعدد عقودهم بدل الترتيب الأبجدي"
        )
        self.frequent_toggle.stateChanged.connect(self.refresh)

        self.search = search_box("بحث بالاسم أو الهاتف أو رقم الجواز…")
        self.search.textChanged.connect(self.refresh)
        header.actions.addWidget(self.frequent_toggle)
        header.actions.addWidget(self.search)

        add_button = primary_button("+ عميل جديد")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)

        layout.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(12)

        # --- الجدول ---
        table_card = Card()
        self.table = DataTable(
            [
                ("full_name", "الاسم"),
                ("phone", "الهاتف"),
                ("national_id", "رقم الجواز/الوطني"),
                ("contracts_count", "عدد العقود"),
                ("last_contract_date", "آخر تعامل"),
            ],
            stretch_column=0,
        )
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.doubleClicked.connect(self._edit)
        table_card.body.addWidget(self.table)
        content.addWidget(table_card, 3)

        # --- لوحة التفاصيل ---
        detail_card = Card()
        self.detail_title = QLabel("اختر عميلاً لعرض تفاصيله")
        self.detail_title.setObjectName("sectionTitle")
        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.contracts_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("plate_number", "اللوحة"),
                ("start_date", "البداية"),
                ("balance_due", "المتبقّي"),
            ],
            stretch_column=0,
        )
        self.contracts_table.setMaximumHeight(190)

        self.attachments_table = DataTable(
            [("file_name", "المرفق"), ("kind", "النوع"), ("uploaded_at", "تاريخ الإضافة")],
            stretch_column=0,
        )
        self.attachments_table.setMaximumHeight(150)

        buttons = QHBoxLayout()
        self.edit_button = QPushButton("تعديل")
        self.edit_button.clicked.connect(self._edit)
        self.attach_button = QPushButton("إضافة مرفق")
        self.attach_button.clicked.connect(self._attach)
        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("danger")
        self.delete_button.clicked.connect(self._delete)

        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.attach_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)

        detail_card.body.addWidget(self.detail_title)
        detail_card.body.addWidget(self.detail_body)
        detail_card.body.addLayout(buttons)
        detail_card.body.addWidget(QLabel("عقود العميل"))
        detail_card.body.addWidget(self.contracts_table)
        detail_card.body.addWidget(QLabel("المرفقات"))
        detail_card.body.addWidget(self.attachments_table)
        detail_card.body.addStretch(1)

        content.addWidget(detail_card, 2)
        layout.addLayout(content, 1)

        self._set_detail_enabled(False)

    # ------------------------------------------------------------------
    def _set_detail_enabled(self, enabled):
        self.edit_button.setEnabled(enabled)
        self.attach_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled and session.has_role("admin"))

    def _selected(self):
        customer_id = self.table.selected_id()
        return customers_repo.get(customer_id) if customer_id else None

    def _format(self, row, key):
        if key == "balance_due":
            return money.format_amount(row["balance_due"], self._symbol)
        return row[key] if key in row.keys() else ""

    def _on_select(self):
        customer = self._selected()
        if customer is None:
            self.detail_title.setText("اختر عميلاً لعرض تفاصيله")
            self.detail_body.setText("")
            self._set_detail_enabled(False)
            return

        balance = customers_repo.outstanding_balance(customer["id"])
        history = customers_repo.contracts_of(customer["id"])
        self.detail_title.setText(
            "%s%s" % (customer["full_name"],
                      "  ★ عميل متكرّر" if len(history) >= 2 else "")
        )
        self.detail_body.setText(fix_dates(
            "الهاتف: %s\nرقم الجواز/الوطني: %s\nرخصة القيادة: %s (تنتهي %s)\n"
            "الجنسية: %s\nالعنوان: %s\nالمستحقّ عليه: %s%s\nملاحظات: %s"
            % (
                customer["phone"] or "—",
                customer["national_id"] or "—",
                customer["license_number"] or "—",
                customer["license_expiry"] or "—",
                customer["nationality"] or "—",
                customer["address"] or "—",
                money.format_amount(balance, self._symbol),
                "\n⚠ العميل مُدرج في القائمة السوداء" if customer["is_blacklisted"] else "",
                customer["notes"] or "—",
            )
        ))

        self.contracts_table.fill(customers_repo.contracts_of(customer["id"]), self._format)
        self.attachments_table.fill(customers_repo.attachments_of(customer["id"]))
        self._set_detail_enabled(True)

    # ------------------------------------------------------------------
    def _add(self):
        if CustomerDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit(self):
        customer = self._selected()
        if customer is None:
            return
        if CustomerDialog(self, customer).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _attach(self):
        customer = self._selected()
        if customer is None:
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف المرفق", "",
            "الملفات المدعومة (*.pdf *.png *.jpg *.jpeg *.docx *.txt);;كل الملفات (*)",
        )
        if not path:
            return

        try:
            customers_repo.add_attachment(customer["id"], path)
        except Exception as error:
            show_error(self, error)
            return

        show_info(self, "أُضيف المرفق ونُسخ إلى مجلد بيانات التطبيق.")
        self._on_select()

    def _delete(self):
        customer = self._selected()
        if customer is None:
            return
        if not confirm(self, "هل تريد حذف العميل «%s» نهائياً؟" % customer["full_name"]):
            return

        try:
            customers_repo.delete(customer["id"])
        except Exception as error:
            show_error(self, error)
            return

        show_info(self, "تم حذف العميل.")
        self.refresh()

    def refresh(self):
        try:
            self._symbol = settings_repo.base_currency()["symbol"]
            rows = customers_repo.search(
                self.search.text(),
                order_by="frequent" if self.frequent_toggle.isChecked() else "name",
            )
            self.table.fill(rows, self._format_customer)
        except Exception as error:
            show_error(self, error)

    def _format_customer(self, row, key):
        if key == "last_contract_date":
            return row["last_contract_date"] or "—"
        if key == "contracts_count":
            return row["contracts_count"] or 0
        return row[key] if key in row.keys() else ""

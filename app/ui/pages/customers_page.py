# -*- coding: utf-8 -*-
"""صفحة العملاء: القائمة والبحث والإضافة والتعديل والمرفقات."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ...core import money, session
from ...repositories import customers_repo, settings_repo
from ..widgets.common import (
    ROW_ACTIVE, ROW_DANGER, Card, DataTable, FormDialog, PageHeader, confirm,
    date_field, date_value, fix_dates, optional_date_field, primary_button,
    search_box, show_error, show_info,
)


class CustomerDialog(FormDialog):
    """حوار إضافة عميل أو تعديل بياناته."""

    def __init__(self, parent=None, customer=None):
        super().__init__(
            parent,
            title="تعديل بيانات عميل" if customer else "إضافة عميل جديد",
            width=520,
        )
        self._customer = customer
        form = self.form

        self.full_name = QLineEdit()
        self.phone = QLineEdit()
        self.national_id = QLineEdit()
        self.license_number = QLineEdit()
        self.license_expiry = date_field()
        self.license_issued_by = QLineEdit()
        self.nationality = QLineEdit()
        self.date_of_birth = optional_date_field()
        self.address = QLineEdit()
        self.work_address = QLineEdit()
        self.phone_alt = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(80)
        self.blacklisted = QCheckBox("إدراج العميل في القائمة السوداء (يمنع التعاقد معه)")
        self.blacklist_reason = QLineEdit()
        self.blacklist_reason.setPlaceholderText("سبب الحظر — يراه من يفتح ملفّه لاحقاً")
        self.blacklist_reason.setEnabled(False)
        self.blacklisted.toggled.connect(self.blacklist_reason.setEnabled)

        form.addRow("الاسم الكامل *", self.full_name)
        form.addRow("رقم الهاتف", self.phone)
        form.addRow("هاتف آخر", self.phone_alt)
        form.addRow("رقم الجواز / الرقم الوطني", self.national_id)
        form.addRow("رقم رخصة القيادة", self.license_number)
        form.addRow("تاريخ انتهاء الرخصة", self.license_expiry)
        form.addRow("الرخصة صادرة عن", self.license_issued_by)
        form.addRow("الجنسية", self.nationality)
        form.addRow("تاريخ الميلاد", self.date_of_birth)
        form.addRow("عنوان السكن", self.address)
        form.addRow("عنوان العمل", self.work_address)
        form.addRow("ملاحظات", self.notes)
        form.addRow("", self.blacklisted)
        form.addRow("سبب الحظر", self.blacklist_reason)

        hint = QLabel(
            "الاسم وحده إلزامي. ما بقي يمكن إكماله لاحقاً، ويظهر العميل حتى "
            "تُكمله بشارة «بيانات ناقصة» في جدول العملاء."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.add_buttons(save_text="حفظ", on_save=self._save)

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

        # أعمدة الترحيل ٤: تُقرأ بلا افتراض وجودها، فقاعدة لم تُرقَّ بعد
        # (نافذة بين تحديث الملفات وأول تشغيل) لا تُسقط الحوار كلّه.
        def value(key):
            return (row[key] if key in row.keys() else None) or ""

        self.license_issued_by.setText(value("license_issued_by"))
        self.phone_alt.setText(value("phone_alt"))
        self.work_address.setText(value("work_address"))
        self.blacklist_reason.setText(value("blacklist_reason"))

        from PyQt6.QtCore import QDate

        if row["license_expiry"]:
            self.license_expiry.setDate(QDate.fromString(row["license_expiry"], "yyyy-MM-dd"))
        if value("date_of_birth"):
            self.date_of_birth.setDate(
                QDate.fromString(value("date_of_birth"), "yyyy-MM-dd")
            )

    def data(self):
        return {
            "full_name": self.full_name.text().strip(),
            "phone": self.phone.text().strip() or None,
            "national_id": self.national_id.text().strip() or None,
            "license_number": self.license_number.text().strip() or None,
            # لا يُحفظ تاريخ انتهاء لرخصة لا وجود لها: حقل التاريخ يبدأ من
            # تاريخ اليوم، فعميل الاسم وحده كان يُحفظ برخصة «تنتهي اليوم»
            # فيُنبَّه المكتب على وثيقة لم تُسجَّل أصلاً.
            "license_expiry": (self.license_expiry.date().toString("yyyy-MM-dd")
                               if self.license_number.text().strip() else None),
            "license_issued_by": self.license_issued_by.text().strip() or None,
            "nationality": self.nationality.text().strip() or None,
            # تاريخ ميلاد لم يُكتب يبقى فارغاً: انظر ``optional_date_field``
            "date_of_birth": date_value(self.date_of_birth),
            "address": self.address.text().strip() or None,
            "work_address": self.work_address.text().strip() or None,
            "phone_alt": self.phone_alt.text().strip() or None,
            "notes": self.notes.toPlainText().strip() or None,
            "is_blacklisted": 1 if self.blacklisted.isChecked() else 0,
            # سبب الحظر لا يُحفظ لعميل غير محظور: بقاؤه بعد رفع الحظر يجعل
            # ملفّاً نظيفاً يحمل تهمةً ألغيت.
            "blacklist_reason": (self.blacklist_reason.text().strip() or None
                                 if self.blacklisted.isChecked() else None),
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
        self._read_only = False
        self._detail_enabled = False
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

        self.incomplete_toggle = QCheckBox("الناقصة بياناتهم فقط")
        self.incomplete_toggle.setToolTip(
            "العملاء الذين سُجّلوا باسمهم وحده ولم تُكمل وثائقهم بعد"
        )
        self.incomplete_toggle.stateChanged.connect(self.refresh)

        self.search = search_box("بحث بالاسم أو الهاتف أو رقم الجواز…")
        self.search.textChanged.connect(self.refresh)
        header.actions.addWidget(self.frequent_toggle)
        header.actions.addWidget(self.incomplete_toggle)
        header.actions.addWidget(self.search)

        self.add_button = primary_button("+ عميل جديد")
        self.add_button.clicked.connect(self._add)
        header.add_action(self.add_button)

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
                ("completeness", "الملفّ"),
            ],
            stretch_column=0,
        )
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.doubleClicked.connect(self._edit)
        table_card.body.addWidget(self.table)

        # مفتاح الألوان: اللون وحده لا يكفي. موظّفٌ جديد لا يعرف ماذا يعني
        # الأحمر، ومن لا يميّز الألوان لا يرى شيئاً أصلاً — فيُكتب المعنى.
        legend = QLabel(
            "🟥 أحمر: عميل محظور لا يجوز التعاقد معه   ·   "
            "🟩 أخضر: بيده سيارة الآن (عقد مفتوح)"
        )
        legend.setObjectName("hint")
        legend.setWordWrap(True)
        table_card.body.addWidget(legend)
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
        self._detail_enabled = bool(enabled)
        enabled = bool(enabled) and not self._read_only
        self.edit_button.setEnabled(enabled)
        self.attach_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled and session.has_role("admin"))

    def _refresh_action_state(self):
        self.add_button.setEnabled(not self._read_only)
        self._set_detail_enabled(self._detail_enabled)

    # ------------------------------------------------------------------
    def set_read_only(self, read_only=True):
        """يعطّل أزرار التعديل ويُبقي العرض والطباعة — وضع القفل.

        الأزرار تُعطَّل ولا تُخفى: صاحب المكتب يرى ما كان يفعله ويعلم أن
        التجديد يعيده، ولا يظنّ أن المنظومة فقدت ما كانت تحسنه.
        """
        self._read_only = bool(read_only)
        self._refresh_action_state()


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
                incomplete_only=self.incomplete_toggle.isChecked(),
            )
            self.table.fill(rows, self._format_customer, self._row_color)
        except Exception as error:
            show_error(self, error)

    @staticmethod
    def _row_color(row):
        """لون صفّ العميل: أحمر للمحظور، أخضر لمن بيده سيارة الآن.

        **والأحمر يسبق الأخضر.** محظورٌ يستأجر اليوم ليس حالة اطمئنان بل حالة
        تستدعي انتباهاً فورياً، فلا يجوز أن يُخفي الأخضرُ الحظرَ لأن العميل
        صادف أن له عقداً مفتوحاً.
        """
        if row["is_blacklisted"]:
            return ROW_DANGER
        open_contracts = row["open_contracts"] if "open_contracts" in row.keys() else 0
        return ROW_ACTIVE if open_contracts else None

    def _format_customer(self, row, key):
        if key == "last_contract_date":
            return row["last_contract_date"] or "—"
        if key == "contracts_count":
            return row["contracts_count"] or 0
        if key == "completeness":
            missing = customers_repo.missing_fields(row)
            if not missing:
                return "مكتمل"
            # تسمية ما ينقص لا مجرّد «ناقص»: الموظّف يعرف ماذا يطلب من العميل
            return "ناقص: " + "، ".join(missing)
        value = row[key] if key in row.keys() else ""
        return "—" if value in (None, "") else value

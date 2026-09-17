# -*- coding: utf-8 -*-
"""صفحة المستخدمين وسجلّ التدقيق — للمدير فقط."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from ... import config
from ...core import audit, session
from ...repositories import users_repo
from ..widgets.common import (
    Card, DataTable, FormDialog, PageHeader, combo, confirm,
    primary_button, show_error, show_info,
)


class UserDialog(FormDialog):
    """حوار إضافة مستخدم أو تعديل بياناته."""
    def __init__(self, parent=None, user_row=None):
        super().__init__(parent, title="تعديل مستخدم" if user_row else "إضافة مستخدم جديد", width=460)
        self._user_row = user_row


        form = self.form

        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.phone = QLineEdit()
        self.role = combo(list(config.ROLE_LABELS.items()))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.active = combo([(1, "فعّال"), (0, "معطَّل")])

        form.addRow("اسم المستخدم *", self.username)
        form.addRow("الاسم الكامل *", self.full_name)
        form.addRow("رقم الهاتف", self.phone)
        form.addRow("الصلاحية *", self.role)
        if user_row is None:
            form.addRow("كلمة المرور *", self.password)
        else:
            form.addRow("حالة الحساب", self.active)

        hint = QLabel(
            "«مدير»: صلاحية كاملة تشمل التقارير المالية وإدارة المستخدمين والنسخ الاحتياطي.\n"
            "«موظّف»: العقود والعملاء والسيارات والدفعات فقط."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.add_buttons(save_text="حفظ", on_save=self._save)

        if user_row:
            self._load(user_row)

    def _load(self, row):
        self.username.setText(row["username"])
        self.username.setEnabled(False)  # اسم المستخدم هوية ثابتة لا تُغيَّر
        self.full_name.setText(row["full_name"])
        self.phone.setText(row["phone"] or "")

        index = self.role.findData(row["role"])
        if index >= 0:
            self.role.setCurrentIndex(index)

        index = self.active.findData(1 if row["is_active"] else 0)
        if index >= 0:
            self.active.setCurrentIndex(index)

    def _save(self):
        try:
            if self._user_row:
                users_repo.update(
                    self._user_row["id"],
                    full_name=self.full_name.text().strip(),
                    role=self.role.currentData(),
                    phone=self.phone.text().strip() or "",
                    is_active=self.active.currentData(),
                )
            else:
                users_repo.create(
                    self.username.text().strip(),
                    self.full_name.text().strip(),
                    self.password.text(),
                    self.role.currentData(),
                    self.phone.text().strip() or None,
                )
        except Exception as error:
            show_error(self, error)
            return
        self.accept()


class UsersPage(QWidget):
    """إدارة الحسابات وعرض سجلّ التدقيق."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = PageHeader("المستخدمون", "الحسابات والصلاحيات وسجلّ العمليات")

        add_button = primary_button("+ مستخدم جديد")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)

        layout.addWidget(header)

        tabs = QTabWidget()

        # --- تبويب المستخدمين ---
        users_tab = QWidget()
        users_layout = QVBoxLayout(users_tab)
        users_layout.setContentsMargins(12, 12, 12, 12)

        self.table = DataTable(
            [
                ("full_name", "الاسم"),
                ("username", "اسم المستخدم"),
                ("role", "الصلاحية"),
                ("phone", "الهاتف"),
                ("is_active", "الحالة"),
                ("last_login_at", "آخر دخول"),
            ],
            stretch_column=0,
        )
        self.table.doubleClicked.connect(self._edit)

        buttons = QHBoxLayout()
        edit_button = QPushButton("تعديل")
        edit_button.clicked.connect(self._edit)
        reset_button = QPushButton("إعادة ضبط كلمة المرور")
        reset_button.clicked.connect(self._reset_password)
        mine_button = QPushButton("تغيير كلمة مروري")
        mine_button.clicked.connect(self._change_own_password)
        buttons.addWidget(edit_button)
        buttons.addWidget(reset_button)
        buttons.addWidget(mine_button)
        buttons.addStretch(1)

        users_layout.addWidget(self.table)
        users_layout.addLayout(buttons)
        tabs.addTab(users_tab, "الحسابات")

        # --- تبويب سجلّ التدقيق ---
        audit_tab = QWidget()
        audit_layout = QVBoxLayout(audit_tab)
        audit_layout.setContentsMargins(12, 12, 12, 12)

        self.audit_table = DataTable(
            [
                ("created_at", "الوقت"),
                ("username", "المستخدم"),
                ("action", "العملية"),
                ("entity", "العنصر"),
                ("entity_id", "المعرّف"),
                ("details", "التفاصيل"),
            ],
            stretch_column=5,
        )
        audit_layout.addWidget(self.audit_table)
        tabs.addTab(audit_tab, "سجلّ التدقيق")

        card = Card(margins=(6, 6, 6, 6))
        card.body.addWidget(tabs)
        layout.addWidget(card, 1)

    # ------------------------------------------------------------------
    def _format_user(self, row, key):
        if key == "role":
            return config.ROLE_LABELS.get(row["role"], row["role"])
        if key == "is_active":
            return "فعّال" if row["is_active"] else "معطَّل"
        if key == "last_login_at":
            return str(row["last_login_at"])[:16] if row["last_login_at"] else "لم يدخل بعد"
        return row[key] if key in row.keys() else ""

    def _format_audit(self, row, key):
        if key == "action":
            return audit.ACTION_LABELS.get(row["action"], row["action"])
        if key == "entity":
            return audit.ENTITY_LABELS.get(row["entity"], row["entity"])
        if key == "created_at":
            return str(row["created_at"])[:19]
        return row[key] if key in row.keys() else ""

    def _selected(self):
        user_id = self.table.selected_id()
        return users_repo.get(user_id) if user_id else None

    def _add(self):
        if UserDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit(self):
        row = self._selected()
        if row is None:
            show_error(self, "اختر مستخدماً أولاً.")
            return
        if UserDialog(self, row).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _ask_password(self, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        first = QLineEdit()
        first.setEchoMode(QLineEdit.EchoMode.Password)
        second = QLineEdit()
        second.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("كلمة المرور الجديدة", first)
        form.addRow("تأكيد كلمة المرور", second)
        buttons = QHBoxLayout()
        save = primary_button("حفظ")
        save.clicked.connect(dialog.accept)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(dialog.reject)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if first.text() != second.text():
            show_error(self, "كلمتا المرور غير متطابقتين.")
            return None
        return first.text()

    def _reset_password(self):
        row = self._selected()
        if row is None:
            show_error(self, "اختر مستخدماً أولاً.")
            return
        if not confirm(self, "إعادة ضبط كلمة مرور «%s»؟" % row["full_name"]):
            return

        password = self._ask_password("إعادة ضبط كلمة المرور")
        if password is None:
            return

        try:
            users_repo.reset_password(row["id"], password)
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "تم الضبط. سيُطلب من المستخدم تغييرها عند أول دخول.")

    def _change_own_password(self):
        password = self._ask_password("تغيير كلمة المرور")
        if password is None:
            return
        try:
            users_repo.change_password(session.current_user_id(), password)
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "تم تغيير كلمة المرور.")

    def refresh(self):
        try:
            self.table.fill(users_repo.list_all(), self._format_user)
            self.audit_table.fill(audit.recent(300), self._format_audit)
        except Exception as error:
            show_error(self, error)

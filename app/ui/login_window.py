# -*- coding: utf-8 -*-
"""شاشة تسجيل الدخول.

تُعرض قبل أي شيء آخر، ولا تُفتح النافذة الرئيسية إلّا بعد نجاح المصادقة.
إن كان الحساب مُلزَماً بتغيير كلمة المرور (كحساب المدير الأول)، يُفتح حوار
التغيير فوراً ولا يمكن تخطّيه.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QVBoxLayout, QWidget,
)

from .. import config
from ..core import session
from ..repositories import users_repo
from .widgets.common import Card, primary_button, show_error, show_info


class ChangePasswordDialog(QDialog):
    """حوار تغيير كلمة المرور — يُستخدم للإلزام الأول ولتغيير المستخدم لكلمته."""

    def __init__(self, user_id, parent=None, forced=False):
        super().__init__(parent)
        self._user_id = user_id
        self._forced = forced

        self.setWindowTitle("تغيير كلمة المرور")
        self.setMinimumWidth(420)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(self)

        if forced:
            notice = QLabel(
                "لأسباب أمنية يجب تغيير كلمة المرور الافتراضية قبل استخدام المنظومة."
            )
            notice.setWordWrap(True)
            notice.setObjectName("hint")
            layout.addWidget(notice)

        form = QFormLayout()
        form.setSpacing(10)

        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("كلمة المرور الجديدة", self.new_password)
        form.addRow("تأكيد كلمة المرور", self.confirm_password)
        layout.addLayout(form)

        self.hint = QLabel(
            "يجب ألّا تقلّ عن %d محارف، وأن تحتوي على حرف ورقم على الأقل."
            % config.MIN_PASSWORD_LENGTH
        )
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        buttons = QHBoxLayout()
        save = primary_button("حفظ")
        save.clicked.connect(self._save)
        buttons.addStretch(1)
        buttons.addWidget(save)

        if not forced:
            from PyQt6.QtWidgets import QPushButton

            cancel = QPushButton("إلغاء")
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)

        layout.addLayout(buttons)

    def _save(self):
        new = self.new_password.text()
        confirm = self.confirm_password.text()

        if new != confirm:
            show_error(self, "كلمتا المرور غير متطابقتين.")
            return

        try:
            users_repo.change_password(self._user_id, new)
        except ValueError as error:
            show_error(self, error)
            return

        show_info(self, "تم تغيير كلمة المرور بنجاح.")
        self.accept()

    def closeEvent(self, event):
        # لا يجوز إغلاق الحوار الإلزامي دون تغيير فعلي لكلمة المرور
        if self._forced and self.result() != QDialog.DialogCode.Accepted:
            event.ignore()
            return
        super().closeEvent(event)


class LoginWindow(QWidget):
    """نافذة الدخول: لوحة ترحيب على اليمين ونموذج الدخول على اليسار."""

    logged_in = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تسجيل الدخول — %s" % config.APP_TITLE_AR)
        self.setMinimumSize(860, 520)
        self._build()

    def _build(self):
        outer = QGridLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)

        # --- لوحة الهوية البصرية ---
        brand = QWidget()
        brand.setObjectName("loginBrand")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(30, 40, 30, 40)
        brand_layout.setSpacing(12)

        title = QLabel(config.APP_TITLE_AR)
        title.setObjectName("loginBrandTitle")
        title.setWordWrap(True)

        description = QLabel(
            "إدارة متكاملة للعملاء والسيارات وعقود الإيجار والمدفوعات،\n"
            "مع نسخ احتياطي تلقائي على Google Drive."
        )
        description.setObjectName("loginBrandText")
        description.setWordWrap(True)

        version = QLabel("الإصدار %s" % config.APP_VERSION)
        version.setObjectName("loginBrandText")

        brand_layout.addStretch(1)
        brand_layout.addWidget(title)
        brand_layout.addWidget(description)
        brand_layout.addStretch(2)
        brand_layout.addWidget(version)

        # --- نموذج الدخول ---
        panel = Card(margins=(32, 32, 32, 32), spacing=14)

        heading = QLabel("تسجيل الدخول")
        heading.setObjectName("loginTitle")

        self.username = QLineEdit()
        self.username.setPlaceholderText("اسم المستخدم")
        self.username.setMinimumHeight(38)

        self.password = QLineEdit()
        self.password.setPlaceholderText("كلمة المرور")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMinimumHeight(38)

        self.error_label = QLabel("")
        self.error_label.setObjectName("loginError")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.submit = primary_button("دخول")
        self.submit.setMinimumHeight(40)
        self.submit.clicked.connect(self.attempt_login)

        self.password.returnPressed.connect(self.attempt_login)
        self.username.returnPressed.connect(lambda: self.password.setFocus())

        panel.body.addWidget(heading)
        panel.body.addSpacing(6)
        panel.body.addWidget(QLabel("اسم المستخدم"))
        panel.body.addWidget(self.username)
        panel.body.addWidget(QLabel("كلمة المرور"))
        panel.body.addWidget(self.password)
        panel.body.addWidget(self.error_label)
        panel.body.addSpacing(6)
        panel.body.addWidget(self.submit)
        panel.body.addStretch(1)

        outer.addWidget(panel, 0, 0)
        outer.addWidget(brand, 0, 1)
        outer.setColumnStretch(0, 3)
        outer.setColumnStretch(1, 2)

    # -- السلوك -------------------------------------------------------------
    def _show_error(self, message):
        self.error_label.setText(str(message))
        self.error_label.setVisible(True)

    def attempt_login(self):
        self.error_label.setVisible(False)
        username = self.username.text().strip()
        password = self.password.text()

        if not username or not password:
            self._show_error("أدخل اسم المستخدم وكلمة المرور.")
            return

        self.submit.setEnabled(False)
        try:
            user = users_repo.authenticate(username, password)
        except users_repo.AuthError as error:
            self._show_error(error)
            self.password.clear()
            self.password.setFocus()
            return
        except Exception as error:  # خطأ غير متوقّع: يُعرض كما هو لا يُبتلع
            self._show_error("تعذّر تسجيل الدخول: %s" % error)
            return
        finally:
            self.submit.setEnabled(True)

        if users_repo.must_change_password(user.id):
            dialog = ChangePasswordDialog(user.id, self, forced=True)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                session.logout()
                self._show_error("يجب تغيير كلمة المرور للمتابعة.")
                return

        self.password.clear()
        self.logged_in.emit(user)

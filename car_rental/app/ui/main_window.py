# -*- coding: utf-8 -*-
"""النافذة الرئيسية: شريط تنقّل جانبي وصفحات متبدّلة.

بنية الواجهة: ``QStackedWidget`` يحمل كل الصفحات، وأزرار الشريط الجانبي
تبدّل بينها. الصفحات تُبنى مرّة واحدة عند الإقلاع وتُحدَّث عند الظهور
(دالة ``refresh``)، فالتنقّل بينها فوري بلا إعادة بناء.

الصلاحيات: صفحات المدير لا تُضاف أصلاً إلى الشريط في حساب الموظّف، فوق
تحقّق الصلاحية في طبقة الخدمة.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QStatusBar, QVBoxLayout, QWidget,
)

from .. import config
from ..core import arabic, db, features, session
from ..services.backup.scheduler import BackupScheduler
from .activation_window import ActivationWindow, SubscriptionPage
from .pages.alerts_page import AlertsPage
from .pages.backup_page import BackupPage
from .pages.contracts_page import ContractsPage
from .pages.customers_page import CustomersPage
from .pages.dashboard_page import DashboardPage
from .pages.maintenance_page import MaintenancePage
from .pages.reports_page import ReportsPage
from .pages.settings_page import SettingsPage
from .pages.users_page import UsersPage
from .pages.vehicles_page import VehiclesPage
from .widgets.common import confirm, show_error, show_info


class MainWindow(QMainWindow):
    """نافذة التطبيق الرئيسية بعد تسجيل الدخول."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user

        self.setWindowTitle(config.APP_TITLE_AR)
        self.resize(1280, 760)
        self.setMinimumSize(1060, 640)

        self._pages = []
        self._build()
        self._start_scheduler()

    # ------------------------------------------------------------------
    # البناء
    # ------------------------------------------------------------------
    def _build(self):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        sidebar = self._build_sidebar()

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(self._status_line())

        self._register_pages()
        if self._pages:
            self._nav_buttons.buttons()[0].setChecked(True)
            self._switch(0)

    def _status_line(self):
        """سطر الحالة: المستخدم وصلاحيته ونسخة الاشتراك وما تبقّى منها."""
        from ..services import subscription

        parts = [
            "مرحباً %s" % self.user.full_name,
            "الصلاحية: %s" % config.ROLE_LABELS.get(self.user.role, self.user.role),
            features.tier_label(),
        ]
        try:
            status = subscription.status()
            if status.is_expiring_soon:
                parts.append("⚠ تبقّى %s على انتهاء الاشتراك"
                             % arabic.days(max(status.days_left, 0)))
        except Exception:
            pass
        return "  —  ".join(parts)

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)

        self._sidebar_layout = QVBoxLayout(sidebar)
        self._sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self._sidebar_layout.setSpacing(0)

        title = QLabel("مكتب إيجار السيارات")
        title.setObjectName("sidebarTitle")
        title.setWordWrap(True)

        subtitle = QLabel("منظومة الإدارة المتكاملة")
        subtitle.setObjectName("sidebarSubtitle")

        self._sidebar_layout.addWidget(title)
        self._sidebar_layout.addWidget(subtitle)

        self._nav_buttons = QButtonGroup(self)
        self._nav_buttons.setExclusive(True)

        self._nav_container = QVBoxLayout()
        self._nav_container.setSpacing(0)
        self._sidebar_layout.addLayout(self._nav_container)
        self._sidebar_layout.addStretch(1)

        user_box = QLabel(
            "%s\n%s" % (self.user.full_name, config.ROLE_LABELS.get(self.user.role, ""))
        )
        user_box.setObjectName("userBox")
        self._sidebar_layout.addWidget(user_box)

        logout = QPushButton("تسجيل الخروج")
        logout.setObjectName("navButton")
        logout.setCheckable(False)
        logout.clicked.connect(self._logout)
        self._sidebar_layout.addWidget(logout)
        self._sidebar_layout.addSpacing(10)

        return sidebar

    def _register_pages(self):
        """يضيف الصفحات المسموحة لصلاحية المستخدم الحالي."""
        # (العنوان، الصفحة، الأدوار، الميزة المطلوبة أو None)
        entries = [
            ("لوحة المعلومات", DashboardPage, ("admin", "staff"), None),
            ("العقود", ContractsPage, ("admin", "staff"), "contracts"),
            ("العملاء", CustomersPage, ("admin", "staff"), "customers"),
            ("السيارات", VehiclesPage, ("admin", "staff"), "vehicles"),
            ("الصيانة والمخالفات", MaintenancePage, ("admin", "staff"), "maintenance"),
            ("التنبيهات", AlertsPage, ("admin", "staff"), "alerts"),
            ("التقارير", ReportsPage, ("admin",), "reports"),
            ("المستخدمون", UsersPage, ("admin",), "multi_user"),
            ("النسخ الاحتياطي", BackupPage, ("admin",), "cloud_backup"),
            ("الاشتراك", SubscriptionPage, ("admin",), None),
            ("الإعدادات", SettingsPage, ("admin",), None),
        ]

        for label, page_class, roles, feature in entries:
            if self.user.role not in roles:
                continue
            # صفحة خارج النسخة الحالية لا تُبنى أصلاً: لا مساحة ولا زمن إقلاع
            if feature and not features.has_feature(feature):
                continue

            page = page_class(self)
            index = self.stack.addWidget(page)
            self._pages.append(page)

            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _, i=index: self._switch(i))

            self._nav_buttons.addButton(button, index)
            self._nav_container.addWidget(button)

    # ------------------------------------------------------------------
    # السلوك
    # ------------------------------------------------------------------
    def _switch(self, index):
        self.stack.setCurrentIndex(index)
        page = self.stack.widget(index)
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as error:
                show_error(self, "تعذّر تحديث الصفحة: %s" % error)

    def refresh_all(self):
        """يحدّث كل الصفحات — يُستدعى بعد عملية تمسّ أكثر من صفحة."""
        for page in self._pages:
            if hasattr(page, "refresh"):
                try:
                    page.refresh()
                except Exception:
                    continue

    def goto_page(self, page_class):
        """ينتقل إلى صفحة بنوعها — يُستخدم من روابط لوحة المعلومات."""
        for index in range(self.stack.count()):
            if isinstance(self.stack.widget(index), page_class):
                button = self._nav_buttons.button(index)
                if button:
                    button.setChecked(True)
                self._switch(index)
                return True
        return False

    # ------------------------------------------------------------------
    # النسخ الاحتياطي التلقائي
    # ------------------------------------------------------------------
    def _start_scheduler(self):
        self.scheduler = BackupScheduler(self)
        self.scheduler.backup_started.connect(
            lambda mode: self.statusBar().showMessage("جارٍ رفع النسخة الاحتياطية…")
        )
        self.scheduler.backup_finished.connect(self._on_backup_finished)
        self.scheduler.backup_failed.connect(self._on_backup_failed)

        # الجدولة للمدير فقط: النسخ عملية على مستوى المنظومة
        if self.user.is_admin:
            self.scheduler.start()

    def _on_backup_finished(self, result):
        self.statusBar().showMessage(
            "اكتملت النسخة الاحتياطية: %s" % result.get("file_name", ""), 10000
        )
        for page in self._pages:
            if isinstance(page, BackupPage):
                page.refresh()

    def _on_backup_failed(self, message):
        self.statusBar().showMessage("تعذّر إتمام النسخة الاحتياطية: %s" % message, 15000)

    # ------------------------------------------------------------------
    # الإغلاق
    # ------------------------------------------------------------------
    def _logout(self):
        if not confirm(self, "هل تريد تسجيل الخروج؟"):
            return
        session.logout()
        self.close()
        show_info(self, "تم تسجيل الخروج. أغلق التطبيق أو أعد تشغيله لتسجيل دخول آخر.",
                  title="تسجيل الخروج")

    def closeEvent(self, event):
        if hasattr(self, "scheduler"):
            if self.scheduler.is_running():
                if not confirm(
                    self,
                    "هناك عملية نسخ احتياطي جارية. الإغلاق الآن قد يُلغيها. هل تريد الإغلاق؟",
                ):
                    event.ignore()
                    return
            self.scheduler.stop()

        db.close_connection()
        super().closeEvent(event)

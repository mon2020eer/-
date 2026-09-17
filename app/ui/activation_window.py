# -*- coding: utf-8 -*-
"""شاشة التفعيل والاشتراك.

تظهر في ثلاث حالات:
    • أول تشغيل: اختيار النسخة لبدء الفترة التجريبية.
    • انتهاء التجربة أو الاشتراك: شاشة التجديد.
    • من داخل التطبيق: لعرض حالة الاشتراك أو إدخال مفتاح جديد.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import config
from ..core import arabic, features, licensing
from ..services import subscription
from .widgets.common import LRM, Card, fix_dates, primary_button, show_error, show_info

# ما يُعرض في بطاقة كل نسخة — ليست قائمة تقنية بل ما يفهمه صاحب المكتب
TIER_HIGHLIGHTS = {
    features.TIER_BASIC: [
        "السيارات والعملاء وعقود الإيجار كاملة",
        "إصدار وتعديل وتجديد وتمديد وإنهاء",
        "الحجز المسبق ومنع تأجير السيارة مرّتين",
        "طباعة العقد PDF بالعربية",
        "العربون والدفعات الجزئية",
        "بالدينار الليبي · حتى %d سيارة · مستخدم واحد" % features.BASIC_VEHICLE_LIMIT,
    ],
    features.TIER_PRO: [
        "كل ما في النسخة الأساسية، بلا حدّ للسيارات",
        "التقارير المالية وتصدير Excel/CSV",
        "النسخ الاحتياطي التلقائي على Google Drive",
        "الصيانة والمخالفات المرورية",
        "الاحتساب بالساعة عند الإرجاع المبكّر",
        "تعدّد المستخدمين والعملات وسجلّ التدقيق",
    ],
}


class TierCard(QFrame):
    """بطاقة نسخة قابلة للاختيار."""

    chosen = pyqtSignal(str)

    def __init__(self, tier, price, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._tier = tier

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        title = QLabel(features.TIER_LABELS[tier])
        title.setObjectName("sectionTitle")

        price_label = QLabel(price)
        price_label.setObjectName("statCardValue")
        price_label.setStyleSheet(
            "color: %s;" % ("#2f6fed" if tier == features.TIER_PRO else "#16a34a")
        )

        layout.addWidget(title)
        layout.addWidget(price_label)

        for line in TIER_HIGHLIGHTS[tier]:
            item = QLabel("✓  " + line)
            item.setWordWrap(True)
            item.setObjectName("hint")
            layout.addWidget(item)

        layout.addStretch(1)

        button = primary_button("تجربة هذه النسخة %s" % arabic.days(licensing.TRIAL_DAYS))
        button.clicked.connect(lambda: self.chosen.emit(self._tier))
        layout.addWidget(button)


class ActivationWindow(QWidget):
    """نافذة التفعيل: اختيار نسخة أو إدخال مفتاح اشتراك."""

    activated = pyqtSignal(object)

    def __init__(self, status=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("الاشتراك — %s" % config.APP_TITLE_AR)
        self.setMinimumSize(900, 620)
        self._status = status or subscription.status()
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 26)
        outer.setSpacing(16)

        self.heading = QLabel("")
        self.heading.setObjectName("pageTitle")
        self.message = QLabel("")
        self.message.setObjectName("pageSubtitle")
        self.message.setWordWrap(True)

        outer.addWidget(self.heading)
        outer.addWidget(self.message)

        # --- بطاقتا النسختين ---
        # البطاقتان داخل حاوية واحدة لا في تخطيط مباشر: إخفاء الحاوية يطوي
        # مساحتها كلّها، فلا تبقى فجوة بيضاء في شاشة التجديد.
        self.tiers_box = QWidget()
        self.tiers_row = QHBoxLayout(self.tiers_box)
        self.tiers_row.setContentsMargins(0, 0, 0, 0)
        self.tiers_row.setSpacing(14)

        self.basic_card = TierCard(features.TIER_BASIC, "١٢٠ د.ل / شهر")
        self.pro_card = TierCard(features.TIER_PRO, "٢٨٠ د.ل / شهر")
        for card in (self.basic_card, self.pro_card):
            card.chosen.connect(self._start_trial)
            self.tiers_row.addWidget(card)

        outer.addWidget(self.tiers_box, 1)

        # --- إدخال المفتاح ---
        key_card = Card()
        key_title = QLabel("لديك مفتاح اشتراك؟")
        key_title.setObjectName("sectionTitle")

        machine_row = QHBoxLayout()
        machine_label = QLabel("بصمة هذا الجهاز (أرسلها عند الشراء):")
        machine_label.setObjectName("hint")

        self.machine_value = QLabel(subscription.machine_id())
        self.machine_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.machine_value.setStyleSheet(
            "font-family: monospace; font-size: 15px; font-weight: bold;"
        )
        copy_button = QPushButton("نسخ")
        copy_button.clicked.connect(self._copy_machine_id)

        machine_row.addWidget(machine_label)
        machine_row.addWidget(self.machine_value)
        machine_row.addWidget(copy_button)
        machine_row.addStretch(1)

        self.key_input = QPlainTextEdit()
        # علامة LRM حول «CR-» وإلّا عُرضت الشرطة قبل الحرفين في فقرة عربية
        self.key_input.setPlaceholderText(
            "ألصق مفتاح الاشتراك هنا (يبدأ بـ %s%s%s)…" % (LRM, licensing.KEY_PREFIX, LRM)
        )
        self.key_input.setMaximumHeight(80)

        activate_button = primary_button("تفعيل الاشتراك")
        activate_button.clicked.connect(self._activate)

        key_card.body.addWidget(key_title)
        key_card.body.addLayout(machine_row)
        key_card.body.addWidget(self.key_input)
        key_card.body.addWidget(activate_button)

        key_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(key_card)

        # يبتلع الفراغ حين تُخفى بطاقتا النسختين، فتبقى بطاقة المفتاح في أعلى
        # الشاشة بحجمها الطبيعي بدل أن تتمدّد على فراغ أبيض
        self.filler = QWidget()
        self.filler.setSizePolicy(QSizePolicy.Policy.Preferred,
                                  QSizePolicy.Policy.Expanding)
        outer.addWidget(self.filler, 1)

        # --- أزرار أسفل ---
        bottom = QHBoxLayout()
        self.continue_button = QPushButton("متابعة إلى البرنامج")
        self.continue_button.clicked.connect(self._continue)
        self.backup_button = QPushButton("أخذ نسخة احتياطية من بياناتي")
        self.backup_button.clicked.connect(self._local_backup)
        self.backup_button.setToolTip(
            "بياناتك ملكك دائماً، ويمكنك حفظها حتى مع انتهاء الاشتراك"
        )

        bottom.addWidget(self.continue_button)
        bottom.addWidget(self.backup_button)
        bottom.addStretch(1)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def refresh(self):
        """يعيد ضبط الشاشة على حالة الاشتراك الحالية."""
        status = self._status
        self.machine_value.setText(subscription.machine_id())

        headings = {
            "none": "مرحباً بك — اختر نسختك",
            "trial": "فترة تجريبية جارية",
            "active": "اشتراكك فعّال",
            "expired": "انتهى الاشتراك",
            "invalid": "تعذّر التحقّق من الاشتراك",
        }
        self.heading.setText(headings.get(status.state, "الاشتراك"))
        self.message.setText(fix_dates(status.message))

        # بطاقتا التجربة لا تظهران إلّا لمن لم يجرّب بعد
        show_tiers = status.state == "none"
        self.tiers_box.setVisible(show_tiers)
        self.filler.setVisible(not show_tiers)

        self.continue_button.setVisible(status.is_usable)
        self.continue_button.setText(
            "متابعة إلى البرنامج (%s)" % features.TIER_LABELS.get(status.tier, "")
        )
        # وضع القفل يُبقي النسخ الاحتياطي متاحاً: بيانات المكتب ملك صاحبه
        self.backup_button.setVisible(not status.is_usable)

    # ------------------------------------------------------------------
    def _start_trial(self, tier):
        try:
            self._status = subscription.start_trial(tier)
        except Exception as error:
            show_error(self, error)
            return

        show_info(
            self,
            "بدأت الفترة التجريبية لـ%s لمدّة %s.\n"
            "يمكنك استعمال البرنامج كاملاً خلالها."
            % (features.TIER_LABELS[tier], arabic.days(licensing.TRIAL_DAYS)),
        )
        self.refresh()
        self.activated.emit(self._status)

    def _activate(self):
        key = self.key_input.toPlainText().strip()
        if not key:
            show_error(self, "ألصق مفتاح الاشتراك أولاً.")
            return

        try:
            self._status = subscription.activate(key)
        except Exception as error:
            show_error(self, error)
            return

        show_info(
            self,
            fix_dates("تم تفعيل %s.\nالاشتراك ساري حتى %s."
                      % (features.TIER_LABELS.get(self._status.tier, ""),
                         self._status.expires_on)),
        )
        self.key_input.clear()
        self.refresh()
        self.activated.emit(self._status)

    def _copy_machine_id(self):
        QApplication.clipboard().setText(subscription.machine_id())
        show_info(self, "نُسخت بصمة الجهاز. أرسلها لمزوّد البرنامج.", title="تم النسخ")

    def _local_backup(self):
        from ..services.backup import backup_service

        try:
            path = backup_service.create_local_snapshot()
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "حُفظت نسخة كاملة من بياناتك في:\n%s" % path)

    def _continue(self):
        self.activated.emit(self._status)


class SubscriptionPage(QWidget):
    """صفحة الاشتراك داخل التطبيق: الحالة والتجديد ونقل الترخيص."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        from .widgets.common import DataTable, PageHeader  # noqa: F401

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        self.header = PageHeader("الاشتراك", "حالة اشتراكك ومزايا نسختك")
        layout.addWidget(self.header)

        status_card = Card()
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        status_card.body.addWidget(self.status_label)

        buttons = QHBoxLayout()
        renew = primary_button("إدخال مفتاح تجديد")
        renew.clicked.connect(self._open_activation)
        transfer = QPushButton("نقل الترخيص إلى جهاز آخر")
        transfer.setToolTip("يحذف المفتاح من هذا الجهاز لتتمكّن من تفعيله على غيره")
        transfer.clicked.connect(self._transfer)
        buttons.addWidget(renew)
        buttons.addWidget(transfer)
        buttons.addStretch(1)
        status_card.body.addLayout(buttons)

        layout.addWidget(status_card)

        upgrade_card = Card()
        upgrade_title = QLabel("مزايا النسخة المتقدّمة")
        upgrade_title.setObjectName("sectionTitle")
        self.upgrade_body = QLabel("")
        self.upgrade_body.setWordWrap(True)
        upgrade_card.body.addWidget(upgrade_title)
        upgrade_card.body.addWidget(self.upgrade_body)
        layout.addWidget(upgrade_card)

        layout.addStretch(1)

    def _open_activation(self):
        self._window = ActivationWindow()
        self._window.show()

    def _transfer(self):
        from .widgets.common import confirm

        if not confirm(
            self,
            "سيُحذف المفتاح من هذا الجهاز ويتوقّف البرنامج عن العمل عليه.\n"
            "استعمل هذا فقط عند الانتقال إلى جهاز آخر. متابعة؟",
        ):
            return
        subscription.deactivate()
        show_info(self, "حُذف المفتاح. أرسل بصمة الجهاز الجديد للحصول على مفتاح بديل.")
        self.refresh()

    def refresh(self):
        status = subscription.status()
        grid = QGridLayout()      # noqa: F841 - محجوز لتوسّع لاحق

        lines = [
            "النسخة الحالية: %s" % features.TIER_LABELS.get(status.tier, ""),
            "الحالة: %s" % {
                "trial": "فترة تجريبية", "active": "اشتراك فعّال",
                "expired": "منتهٍ", "invalid": "غير صالح", "none": "لم يُفعَّل",
            }.get(status.state, status.state),
        ]
        if status.office:
            lines.append("الجهة: %s" % status.office)
        if status.expires_on:
            lines.append("ينتهي في: %s (تبقّى %s)"
                         % (status.expires_on, arabic.days(max(status.days_left, 0))))
        lines.append("بصمة هذا الجهاز: %s" % subscription.machine_id())

        self.status_label.setText(fix_dates("\n".join(lines)))

        missing = features.missing_features()
        if missing:
            self.upgrade_body.setText(
                "\n".join("• " + features.FEATURE_LABELS.get(name, name)
                          for name in missing)
                + "\n\nللترقية راجع مزوّد البرنامج."
            )
        else:
            self.upgrade_body.setText("لديك النسخة المتقدّمة بكل مزاياها.")

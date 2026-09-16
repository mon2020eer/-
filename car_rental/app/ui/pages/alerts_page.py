# -*- coding: utf-8 -*-
"""شاشة التنبيهات: ما انتهى وما يوشك من التأمين والفحص والرخص."""

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...services import alerts
from ..widgets.common import Card, DataTable, PageHeader, combo, primary_button


class AlertsPage(QWidget):
    """قائمة واحدة بكل ما يحتاج تجديداً، مرتَّبة بالأشدّ إلحاحاً."""

    COLUMNS = (
        ("kind", "النوع"),
        ("subject", "الموضوع"),
        ("expiry", "تاريخ الانتهاء"),
        ("left", "المتبقّي"),
        ("severity", "الحالة"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = PageHeader(
            "التنبيهات",
            "تأمين السيارات وفحصها الفنّي ورخص قيادة العملاء — ما انتهى وما يوشك",
        )
        layout.addWidget(header)

        # --- بطاقات العدّ ---
        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.expired_card = self._counter("منتهٍ الآن", "#b91c1c")
        self.soon_card = self._counter("يوشك على الانتهاء", "#c2570c")
        cards.addWidget(self.expired_card)
        cards.addWidget(self.soon_card)
        cards.addStretch(1)
        layout.addLayout(cards)

        # --- المرشِّحات ---
        tools = QHBoxLayout()
        tools.setSpacing(8)

        self.kind_filter = combo(
            [(None, "كل الأنواع")]
            + [(key, label) for key, label in alerts.KIND_LABELS.items()]
        )
        self.kind_filter.currentIndexChanged.connect(self.refresh)

        self.severity_filter = combo([
            (None, "كل الحالات"),
            (alerts.EXPIRED, "المنتهي فقط"),
            (alerts.SOON, "الموشك فقط"),
        ])
        self.severity_filter.currentIndexChanged.connect(self.refresh)

        refresh_button = primary_button("تحديث")
        refresh_button.clicked.connect(self.refresh)

        tools.addWidget(self.kind_filter)
        tools.addWidget(self.severity_filter)
        tools.addWidget(refresh_button)
        tools.addStretch(1)
        layout.addLayout(tools)

        # --- الجدول ---
        card = Card()
        self.table = DataTable(list(self.COLUMNS), stretch_column=1)
        card.body.addWidget(self.table)
        layout.addWidget(card, 1)

        self.empty_label = QLabel("لا توجد تنبيهات — كل الوثائق سارية.")
        self.empty_label.setObjectName("hint")
        layout.addWidget(self.empty_label)

    def _counter(self, label, color):
        card = Card(spacing=2, margins=(16, 12, 16, 12))
        card.setFixedWidth(220)

        value = QLabel("0")
        value.setObjectName("statCardValue")
        value.setStyleSheet("color: %s;" % color)

        title = QLabel(label)
        title.setObjectName("statCardLabel")

        card.body.addWidget(value)
        card.body.addWidget(title)
        card.value_label = value
        return card

    # ------------------------------------------------------------------
    def refresh(self):
        try:
            found = alerts.collect(
                kinds=[self.kind_filter.currentData()]
                if self.kind_filter.currentData() else None,
            )
        except Exception:
            # النسخة الأساسية لا تملك الميزة: الصفحة لا تُبنى أصلاً، وهذا
            # احتياط لئلّا ينهار التحديث إن استُدعي من مسار آخر.
            found = []

        severity = self.severity_filter.currentData()
        rows = [alert for alert in found
                if severity is None or alert.severity == severity]

        self.expired_card.value_label.setText(
            str(sum(1 for a in found if a.severity == alerts.EXPIRED))
        )
        self.soon_card.value_label.setText(
            str(sum(1 for a in found if a.severity == alerts.SOON))
        )

        self.table.fill(rows, self._row)
        self.empty_label.setVisible(not rows)

    @staticmethod
    def _row(alert, key):
        from ...core import arabic

        if key == "kind":
            return alert.kind_label
        if key == "subject":
            return alert.subject
        if key == "expiry":
            return alert.expiry_date
        if key == "left":
            if alert.severity == alerts.EXPIRED:
                return "انتهى منذ %s" % arabic.days(abs(alert.days_left))
            return arabic.days(alert.days_left)
        return alert.severity_label

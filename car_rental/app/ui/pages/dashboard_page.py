# -*- coding: utf-8 -*-
"""لوحة المعلومات: الحالة اللحظية للمكتب في شاشة واحدة.

ما تعرضه مرتَّب بحسب ما يحتاجه الموظّف صباحاً: كم سيارة متاحة الآن، وأي
العقود يجب إغلاقها اليوم، وكم من المال لم يُحصَّل بعد.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import config
from ...core import money
from ...repositories import contracts_repo, settings_repo
from ...services import reporting
from ..widgets.common import (
    Card, DataTable, PageHeader, StatCard, search_box, show_error,
)


class DashboardPage(QWidget):
    """الصفحة الافتتاحية بعد تسجيل الدخول."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)

        self.header = PageHeader("لوحة المعلومات", "نظرة عامّة على حالة المكتب اليوم")

        # بحث سريع يعمل على العقود والسيارات والعملاء معاً
        self.quick_search = search_box("بحث سريع: رقم لوحة، اسم عميل، رقم عقد…")
        self.quick_search.textChanged.connect(self._quick_search)
        self.header.actions.addWidget(self.quick_search)

        layout.addWidget(self.header)

        # --- بطاقات الحالة ---
        cards = QGridLayout()
        cards.setSpacing(12)

        self.card_available = StatCard("سيارات متاحة", "0", accent="#16a34a")
        self.card_rented = StatCard("سيارات مؤجَّرة", "0", accent="#ea580c")
        self.card_maintenance = StatCard("في الصيانة", "0", accent="#4f46e5")
        self.card_open = StatCard("عقود مفتوحة", "0", accent="#2f6fed")
        self.card_revenue = StatCard("إيراد الشهر", "0", accent="#16243c")
        self.card_outstanding = StatCard("مبالغ مستحقّة", "0", accent="#dc2626")

        for column, card in enumerate(
            (self.card_available, self.card_rented, self.card_maintenance,
             self.card_open, self.card_revenue, self.card_outstanding)
        ):
            cards.addWidget(card, 0, column)
            cards.setColumnStretch(column, 1)

        layout.addLayout(cards)

        # --- جدولان جنباً إلى جنب ---
        tables = QHBoxLayout()
        tables.setSpacing(12)

        due_card = Card()
        due_title = QLabel("عقود يجب إغلاقها (اليوم أو متأخّرة)")
        due_title.setObjectName("sectionTitle")
        self.due_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("plate_number", "اللوحة"),
                ("expected_end_date", "تاريخ التسليم"),
                ("balance_due", "المتبقّي"),
            ],
            stretch_column=1,
        )
        due_card.body.addWidget(due_title)
        due_card.body.addWidget(self.due_table)

        unpaid_card = Card()
        unpaid_title = QLabel("أعلى المبالغ غير المحصَّلة")
        unpaid_title.setObjectName("sectionTitle")
        self.unpaid_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("customer_phone", "الهاتف"),
                ("balance_due", "المتبقّي"),
                ("status", "حالة العقد"),
            ],
            stretch_column=1,
        )
        unpaid_card.body.addWidget(unpaid_title)
        unpaid_card.body.addWidget(self.unpaid_table)

        tables.addWidget(due_card, 1)
        tables.addWidget(unpaid_card, 1)
        layout.addLayout(tables, 1)

        # --- نتائج البحث السريع ---
        self.search_card = Card()
        search_title = QLabel("نتائج البحث السريع")
        search_title.setObjectName("sectionTitle")
        self.search_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("plate_number", "اللوحة"),
                ("start_date", "البداية"),
                ("expected_end_date", "الانتهاء"),
                ("status", "الحالة"),
                ("payment_status", "الدفع"),
            ],
            stretch_column=1,
        )
        self.search_card.body.addWidget(search_title)
        self.search_card.body.addWidget(self.search_table)
        self.search_card.setVisible(False)
        layout.addWidget(self.search_card, 1)

    # ------------------------------------------------------------------
    def _format(self, row, key):
        if key == "balance_due":
            return money.format_amount(row["balance_due"], self._symbol)
        if key == "status":
            return config.CONTRACT_STATUS_LABELS.get(row["status"], row["status"])
        if key == "payment_status":
            return config.PAYMENT_STATUS_LABELS.get(row["payment_status"], "")
        return row[key] if key in row.keys() else ""

    def _quick_search(self, text):
        text = (text or "").strip()
        self.search_card.setVisible(bool(text))
        if not text:
            return

        try:
            rows = contracts_repo.search(term=text, limit=100)
        except Exception as error:
            show_error(self, error)
            return

        self.search_table.fill(rows, self._format)

    def refresh(self):
        try:
            summary = reporting.dashboard_summary()
            self._symbol = settings_repo.base_currency()["symbol"]

            fleet = summary["fleet"]
            self.card_available.set_value(fleet["available"], "من إجمالي %d سيارة" % fleet["total"])
            self.card_rented.set_value(fleet["rented"], "نسبة الإشغال %.1f%%" % summary["occupancy"])
            self.card_maintenance.set_value(fleet["maintenance"])
            self.card_open.set_value(
                summary["contracts"]["open"],
                "%d عقد متأخّر الإرجاع" % summary["overdue_count"]
                if summary["overdue_count"] else "لا عقود متأخّرة",
            )
            self.card_revenue.set_value(
                money.format_amount(summary["month_revenue"], self._symbol),
                "المحصَّل: %s" % money.format_amount(summary["month_collected"], self._symbol),
            )
            self.card_outstanding.set_value(
                money.format_amount(summary["outstanding"], self._symbol),
                "على %d عميل" % summary["customers"],
            )

            self.due_table.fill(contracts_repo.due_today_or_overdue(), self._format)
            self.unpaid_table.fill(contracts_repo.unpaid()[:20], self._format)

            self.header.set_subtitle(
                "نظرة عامّة — فترة التقرير: %s إلى %s" % summary["period"]
            )
        except Exception as error:
            show_error(self, "تعذّر تحميل لوحة المعلومات: %s" % error)

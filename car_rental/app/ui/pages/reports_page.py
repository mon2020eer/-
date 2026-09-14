# -*- coding: utf-8 -*-
"""صفحة التقارير المالية والتشغيلية — متاحة للمدير فقط."""

import datetime

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from ... import config
from ...core import money
from ...repositories import settings_repo
from ...services import reporting
from ..widgets.common import (
    Card, DataTable, PageHeader, StatCard, date_field, primary_button, show_error,
    show_info,
)


class ReportsPage(QWidget):
    """تقارير الإيرادات والديون والأسطول مع تصدير CSV."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = self.header = PageHeader("التقارير", "تحليل الإيرادات والديون وأداء الأسطول")

        first_of_month = QDate.currentDate().addDays(-(QDate.currentDate().day() - 1))
        self.start_date = date_field(first_of_month)
        self.end_date = date_field()

        apply_button = primary_button("عرض التقرير")
        apply_button.clicked.connect(self.refresh)

        header.actions.addWidget(QLabel("من"))
        header.actions.addWidget(self.start_date)
        header.actions.addWidget(QLabel("إلى"))
        header.actions.addWidget(self.end_date)
        header.add_action(apply_button)

        layout.addWidget(header)

        # --- ملخّص مالي ---
        cards = QGridLayout()
        cards.setSpacing(12)

        self.card_contracts = StatCard("عدد العقود", "0", accent="#2f6fed")
        self.card_contracted = StatCard("قيمة العقود", "0", accent="#16243c")
        self.card_collected = StatCard("المحصَّل فعلياً", "0", accent="#16a34a")
        self.card_outstanding = StatCard("لم يُحصَّل بعد", "0", accent="#dc2626")
        self.card_maintenance = StatCard("مصاريف الصيانة", "0", accent="#ea580c")
        self.card_net = StatCard("الصافي بعد الصيانة", "0", accent="#4f46e5")

        for column, card in enumerate(
            (self.card_contracts, self.card_contracted, self.card_collected,
             self.card_outstanding, self.card_maintenance, self.card_net)
        ):
            cards.addWidget(card, 0, column)
            cards.setColumnStretch(column, 1)

        layout.addLayout(cards)

        # --- تبويبات التفاصيل ---
        tabs = QTabWidget()

        self.monthly_table = DataTable(
            [("month", "الشهر"), ("contracts", "عدد العقود"), ("revenue", "الإيراد")],
            stretch_column=0,
        )
        tabs.addTab(self._wrap(self.monthly_table), "الإيراد الشهري")

        self.vehicles_table = DataTable(
            [
                ("vehicle_title", "السيارة"),
                ("plate_number", "اللوحة"),
                ("contracts", "عدد العقود"),
                ("days", "أيام التأجير"),
                ("revenue", "الإيراد"),
            ],
            stretch_column=0,
        )
        tabs.addTab(self._wrap(self.vehicles_table), "أداء السيارات")

        self.customers_table = DataTable(
            [
                ("full_name", "العميل"),
                ("phone", "الهاتف"),
                ("contracts", "عدد العقود"),
                ("revenue", "إجمالي التعاقد"),
            ],
            stretch_column=0,
        )
        tabs.addTab(self._wrap(self.customers_table), "أفضل العملاء")

        self.outstanding_table = DataTable(
            [
                ("contract_number", "رقم العقد"),
                ("customer_name", "العميل"),
                ("customer_phone", "الهاتف"),
                ("plate_number", "اللوحة"),
                ("total_amount", "الإجمالي"),
                ("paid_amount", "المدفوع"),
                ("balance_due", "المتبقّي"),
            ],
            stretch_column=1,
        )
        tabs.addTab(self._wrap(self.outstanding_table), "الديون المستحقّة")

        layout.addWidget(tabs, 1)

        # --- التصدير ---
        exports = QHBoxLayout()
        for label, handler in (
            ("تصدير الديون (CSV)", self._export_outstanding),
            ("تصدير الأسطول (CSV)", self._export_fleet),
            ("تصدير العقود (CSV)", self._export_contracts),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            exports.addWidget(button)
        exports.addStretch(1)

        hint = QLabel("ملفات CSV تُفتح مباشرةً في Excel مع دعم كامل للعربية.")
        hint.setObjectName("hint")
        exports.addWidget(hint)

        layout.addLayout(exports)

    @staticmethod
    def _wrap(widget):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(widget)
        return container

    # ------------------------------------------------------------------
    def _period(self):
        return (
            self.start_date.date().toString("yyyy-MM-dd"),
            self.end_date.date().toString("yyyy-MM-dd"),
        )

    def _format(self, row, key):
        if key in ("revenue", "total_amount", "paid_amount", "balance_due"):
            return money.format_amount(row[key], self._symbol)
        if key == "vehicle_title":
            return row["vehicle_title"]
        return row[key] if key in row.keys() else ""

    def _ask_path(self, default_name):
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ الملف", str(config.EXPORTS_DIR / default_name), "ملفات CSV (*.csv)"
        )
        return path

    def _export(self, exporter, default_name):
        path = self._ask_path(default_name)
        if not path:
            return
        try:
            config.ensure_directories()
            exporter(path)
        except Exception as error:
            show_error(self, "تعذّر التصدير: %s" % error)
            return
        show_info(self, "تم التصدير إلى:\n%s" % path)

    def _export_outstanding(self):
        self._export(reporting.export_outstanding_csv, "الديون_المستحقة.csv")

    def _export_fleet(self):
        self._export(reporting.export_fleet_csv, "الأسطول.csv")

    def _export_contracts(self):
        self._export(reporting.export_contracts_csv, "العقود.csv")

    # ------------------------------------------------------------------
    def refresh(self):
        try:
            start, end = self._period()
            if start > end:
                show_error(self, "تاريخ البداية يجب أن يسبق تاريخ النهاية.")
                return

            self._symbol = settings_repo.base_currency()["symbol"]
            report = reporting.revenue_report(start, end)

            self.card_contracts.set_value(report["contracts_count"])
            self.card_contracted.set_value(
                money.format_amount(report["contracted"], self._symbol)
            )
            self.card_collected.set_value(
                money.format_amount(report["collected"], self._symbol)
            )
            self.card_outstanding.set_value(
                money.format_amount(max(report["outstanding"], 0), self._symbol)
            )
            self.card_maintenance.set_value(
                money.format_amount(report["maintenance_cost"], self._symbol)
            )
            self.card_net.set_value(money.format_amount(report["net"], self._symbol))

            self.monthly_table.fill(reporting.monthly_revenue(12), self._format)
            self.vehicles_table.fill(reporting.top_vehicles(start, end, 30), self._format)
            self.customers_table.fill(reporting.top_customers(start, end, 30), self._format)
            self.outstanding_table.fill(reporting.outstanding_report(), self._format)

            days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1
            self.header.set_subtitle("الفترة: %s إلى %s (%d يوم)" % (start, end, days))
        except Exception as error:
            show_error(self, "تعذّر إعداد التقرير: %s" % error)

# -*- coding: utf-8 -*-
"""تقرير أداء وربحية السيارات — «كاشف الحفر المالية».

الشاشة تجيب عن سؤال واحد بلا مقدّمات: **أيّ سيارة تكسب، وأيّها تأكل المال؟**

ولذلك بُنيت على ثلاث طبقات تُقرأ من أعلى إلى أسفل:

    ١. بطاقات الملخّص   — حال الأسطول كلّه في سطر: رأس المال، والإيراد،
                          والتكلفة، والصافي، وعدد الحفر المالية.
    ٢. جدول السيارات    — سطرٌ لكل سيارة، وخليّةُ صافي الربح ملوَّنة:
                          أحمر لمن تأكل المال، وأخضر لمن استردّت ثمنها.
    ٣. لوحة التفاصيل    — لماذا؟ تفصيل التكاليف بأنواعها ودفترها سطراً سطراً.

الترتيب الافتراضي «الأسوأ أولاً» عن قصد: من يفتح التقرير يريد الحفرة لا
قائمةً أبجدية يبحث فيها عنها.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from ... import config
from ...core import arabic, money, session
from ...repositories import expenses_repo, settings_repo, vehicles_repo
from ...services import profitability
from ..widgets.common import (
    Card, DataTable, PageHeader, ROW_ACTIVE, ROW_DANGER, ROW_MUTED, ROW_WARNING,
    StatCard, combo, confirm, fix_dates, primary_button, show_error, show_info,
)
from ..widgets.expense_dialog import ExpenseDialog

# لون خليّة صافي الربح لكل حالة ربحية. الألوان فاتحة والنصّ فوقها داكن،
# فتُقرأ الأرقام ولا يتحوّل الجدول إلى لوحة ألوان.
STATUS_COLORS = {
    profitability.STATUS_MONEY_PIT: ROW_DANGER,     # أحمر: التكلفة تجاوزت الإيراد
    profitability.STATUS_RECOVERING: ROW_WARNING,   # كهرماني: تربح ولم تستردّ ثمنها
    profitability.STATUS_PROFITABLE: ROW_ACTIVE,    # أخضر: استردّت ثمنها وتربح
    profitability.STATUS_IDLE: ROW_MUTED,           # رمادي: لا حركة بعد
}

# أعمدة المبالغ في جدول التقرير — تُنسَّق بعلامة العملة الأساس
_MONEY_KEYS = ("purchase_price", "total_revenue", "total_expenses", "net_profit")


class ProfitabilityPage(QWidget):
    """تقرير ربحية الأسطول وعائد الاستثمار."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._read_only = False
        self._symbol = ""
        self._rows = []
        self._ledger_rows = []
        self._build()

    # ------------------------------------------------------------------
    # البناء
    # ------------------------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        self.header = PageHeader(
            "تقرير أداء وربحية السيارات",
            "أرقام تراكمية منذ تسجيل كل سيارة: ما أنتجته، وما كلّفته، وما تبقّى من ثمنها",
        )

        self.order = combo(list(profitability.ORDER_LABELS))
        self.order.currentIndexChanged.connect(self.refresh)

        self.only_pits = QCheckBox("الحفر المالية فقط")
        self.only_pits.setToolTip("السيارات التي تجاوزت تكاليفُها إيرادَها")
        self.only_pits.stateChanged.connect(self.refresh)

        self.header.actions.addWidget(QLabel("الترتيب"))
        self.header.actions.addWidget(self.order)
        self.header.actions.addWidget(self.only_pits)

        self.add_expense_button = primary_button("+ إضافة مصروف / صيانة")
        self.add_expense_button.clicked.connect(self._add_expense)
        self.header.add_action(self.add_expense_button)

        self.export_button = QPushButton("تصدير التقرير (CSV)")
        self.export_button.clicked.connect(self._export)
        self.header.add_action(self.export_button)

        layout.addWidget(self.header)
        layout.addLayout(self._build_cards())

        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(self._build_table_card(), 3)
        content.addWidget(self._build_detail_card(), 2)
        layout.addLayout(content, 1)

        self._set_detail_enabled(False)

    def _build_cards(self):
        cards = QGridLayout()
        cards.setSpacing(12)

        self.card_fleet = StatCard("عدد السيارات", "0", accent="#2f6fed")
        self.card_invested = StatCard("رأس المال المستثمر", "0", accent="#16243c")
        self.card_revenue = StatCard("إجمالي الإيرادات", "0", accent="#16a34a")
        self.card_expenses = StatCard("إجمالي المصروفات", "0", accent="#ea580c")
        self.card_net = StatCard("صافي الربح التشغيلي", "0", accent="#4f46e5")
        self.card_pits = StatCard("حفر مالية", "0", accent="#dc2626")

        for column, card in enumerate(
            (self.card_fleet, self.card_invested, self.card_revenue,
             self.card_expenses, self.card_net, self.card_pits)
        ):
            cards.addWidget(card, 0, column)
            cards.setColumnStretch(column, 1)

        return cards

    def _build_table_card(self):
        card = Card()
        self.table = DataTable(
            [
                ("vehicle_title", "السيارة"),
                ("plate_number", "رقم اللوحة"),
                ("purchase_price", "تكلفة الشراء"),
                ("contracts_count", "عدد العقود"),
                ("total_revenue", "إجمالي الإيرادات"),
                ("total_expenses", "إجمالي المصروفات"),
                ("net_profit", "صافي الربح التشغيلي"),
                ("recovery_ratio", "استرداد رأس المال"),
                ("profit_status", "التقييم"),
            ],
            stretch_column=0,
        )
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        card.body.addWidget(self.table)

        legend = QLabel(
            "التلوين في خانة صافي الربح:  "
            "أحمر = التكاليف تجاوزت الإيراد (حفرة مال)  ·  "
            "كهرماني = تربح ولم تستردّ ثمن شرائها بعد  ·  "
            "أخضر = استردّت ثمن شرائها كاملاً  ·  "
            "رمادي = لا حركة مسجَّلة بعد."
        )
        legend.setObjectName("hint")
        legend.setWordWrap(True)
        card.body.addWidget(legend)
        return card

    def _build_detail_card(self):
        card = Card()

        self.detail_title = QLabel("اختر سيارة لعرض تفصيل ربحيتها")
        self.detail_title.setObjectName("sectionTitle")

        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)

        buttons = QHBoxLayout()
        self.detail_expense_button = QPushButton("+ مصروف لهذه السيارة")
        self.detail_expense_button.clicked.connect(self._add_expense_for_selected)
        self.edit_expense_button = QPushButton("تعديل المصروف المختار")
        self.edit_expense_button.clicked.connect(self._edit_expense)
        self.delete_expense_button = QPushButton("حذف")
        self.delete_expense_button.setObjectName("danger")
        self.delete_expense_button.clicked.connect(self._delete_expense)

        for button in (self.detail_expense_button, self.edit_expense_button,
                       self.delete_expense_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.breakdown_table = DataTable(
            [
                ("expense_type", "نوع المصروف"),
                ("entries", "عدد الحركات"),
                ("total", "الإجمالي"),
            ],
            stretch_column=0,
        )
        self.breakdown_table.setMaximumHeight(160)

        self.ledger_table = DataTable(
            [
                ("expense_date", "التاريخ"),
                ("expense_type", "النوع"),
                ("amount", "القيمة"),
                ("source", "المصدر"),
                ("notes", "البيان"),
            ],
            stretch_column=4,
        )

        card.body.addWidget(self.detail_title)
        card.body.addWidget(self.detail_body)
        card.body.addLayout(buttons)
        card.body.addWidget(QLabel("تفصيل التكاليف حسب النوع"))
        card.body.addWidget(self.breakdown_table)
        card.body.addWidget(QLabel("دفتر تكاليف السيارة"))
        card.body.addWidget(self.ledger_table, 1)
        return card

    # ------------------------------------------------------------------
    # الحالة
    # ------------------------------------------------------------------
    def set_read_only(self, read_only=True):
        """يعطّل الإدخال ويُبقي القراءة والتصدير — وضع القفل."""
        self._read_only = bool(read_only)
        self.add_expense_button.setEnabled(not self._read_only)
        self.detail_expense_button.setEnabled(not self._read_only)

    def _set_detail_enabled(self, enabled):
        enabled = bool(enabled) and not self._read_only
        self.detail_expense_button.setEnabled(enabled)
        self.edit_expense_button.setEnabled(enabled)
        # حذف المصروف للمدير وحده: رقمٌ يُمحى يجعل سيارة خاسرة تبدو رابحة
        self.delete_expense_button.setEnabled(enabled and session.has_role("admin"))

    def _selected_vehicle_id(self):
        return self.table.selected_id()

    def _selected_ledger_row(self):
        """صفّ دفتر التكاليف المختار، أو ``None``."""
        index = self.ledger_table.selected_row_index()
        if index is None or index >= len(self._ledger_rows):
            return None
        return self._ledger_rows[index]

    # ------------------------------------------------------------------
    # التنسيق
    # ------------------------------------------------------------------
    def _format(self, row, key):
        if key in _MONEY_KEYS:
            if key == "purchase_price" and not row["has_purchase_price"]:
                return "— غير مسجَّلة —"
            return money.format_amount(row[key], self._symbol)
        if key == "recovery_ratio":
            if row["recovery_ratio"] is None:
                return "—"
            return "%s٪" % row["recovery_ratio"]
        if key == "profit_status":
            return config.PROFIT_STATUS_LABELS.get(row["profit_status"], "")
        return row[key] if key in row.keys() else ""

    @staticmethod
    def _cell_color(row, key):
        """لون خليّة صافي الربح وحدها — هي خبرُ السطر."""
        if key != "net_profit":
            return None
        return STATUS_COLORS.get(row["profit_status"])

    def _format_breakdown(self, row, key):
        if key == "expense_type":
            return config.EXPENSE_TYPE_LABELS.get(row["expense_type"], row["expense_type"])
        if key == "total":
            return money.format_amount(row["total"] or 0, self._symbol)
        return row[key] if key in row.keys() else ""

    def _format_ledger(self, row, key):
        if key == "expense_type":
            return config.EXPENSE_TYPE_LABELS.get(row["expense_type"], row["expense_type"])
        if key == "amount":
            symbol = settings_repo.symbol_of(row["currency_code"])
            return money.format_amount(row["amount"], symbol)
        if key == "source":
            return "شاشة الصيانة" if row["source"] == "maintenance" else "إدخال يدوي"
        if key == "notes":
            return (row["notes"] or "—").replace("\n", " · ")
        return row[key] if key in row.keys() else ""

    # ------------------------------------------------------------------
    # الإجراءات
    # ------------------------------------------------------------------
    def _add_expense(self, vehicle=None):
        dialog = ExpenseDialog(self, vehicle=vehicle)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _add_expense_for_selected(self):
        vehicle_id = self._selected_vehicle_id()
        if not vehicle_id:
            show_error(self, "اختر سيارة من الجدول أولاً.")
            return
        self._add_expense(vehicle=vehicles_repo.get(vehicle_id))

    def _edit_expense(self):
        row = self._selected_ledger_row()
        if row is None:
            show_error(self, "اختر حركة من دفتر التكاليف أولاً.")
            return
        if row["source"] == "maintenance":
            show_error(
                self,
                "هذه الحركة قادمة من سجلّ الصيانة، وتُعدَّل من شاشة "
                "«الصيانة والمخالفات» حيث سُجّلت.",
            )
            return

        expense = expenses_repo.get(row["id"])
        if expense is None:
            show_error(self, "المصروف غير موجود.")
            return
        if ExpenseDialog(self, expense=expense).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _delete_expense(self):
        row = self._selected_ledger_row()
        if row is None:
            show_error(self, "اختر حركة من دفتر التكاليف أولاً.")
            return
        if row["source"] == "maintenance":
            show_error(self, "سجلّات الصيانة تُدار من شاشة «الصيانة والمخالفات».")
            return
        if not confirm(self, "حذف هذا المصروف نهائياً؟ سيتغيّر صافي ربح السيارة."):
            return
        try:
            expenses_repo.delete_expense(row["id"])
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "حُذف المصروف وأُعيد احتساب الربحية.")
        self.refresh()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ تقرير الربحية",
            str(config.EXPORTS_DIR / "ربحية_الأسطول.csv"), "ملفات CSV (*.csv)"
        )
        if not path:
            return
        try:
            config.ensure_directories()
            profitability.export_profitability_csv(path, rows=self._rows)
        except Exception as error:
            show_error(self, "تعذّر التصدير: %s" % error)
            return
        show_info(self, "تم التصدير إلى:\n%s" % path)

    # ------------------------------------------------------------------
    # التحديث
    # ------------------------------------------------------------------
    def _on_select(self):
        vehicle_id = self._selected_vehicle_id()
        if not vehicle_id:
            self.detail_title.setText("اختر سيارة لعرض تفصيل ربحيتها")
            self.detail_body.setText("")
            self.breakdown_table.fill([])
            self._ledger_rows = []
            self.ledger_table.fill([])
            self._set_detail_enabled(False)
            return

        row = next((item for item in self._rows if item["vehicle_id"] == vehicle_id), None)
        if row is None:
            self._set_detail_enabled(False)
            return

        self.detail_title.setText(
            fix_dates("%s — %s" % (row["vehicle_title"], row["plate_number"]))
        )
        self.detail_body.setText(fix_dates(self._detail_text(row)))

        self.breakdown_table.fill(
            expenses_repo.totals_by_type(vehicle_id=vehicle_id), self._format_breakdown
        )
        self._ledger_rows = list(expenses_repo.list_ledger(vehicle_id))
        self.ledger_table.fill(self._ledger_rows, self._format_ledger)
        self._set_detail_enabled(True)

    def _detail_text(self, row):
        """نصّ لوحة التفاصيل: الأرقام ثمّ قراءتها بجملة عربية مفهومة."""
        lines = [
            "التقييم: %s" % config.PROFIT_STATUS_LABELS.get(row["profit_status"], ""),
            "تاريخ الشراء: %s" % (row["purchase_date"] or "غير مسجَّل"),
            "تكلفة الشراء: %s" % (
                money.format_amount(row["purchase_price"], self._symbol)
                if row["has_purchase_price"] else "غير مسجَّلة"
            ),
            "عدد العقود: %s خلال %s تأجير"
            % (arabic.contracts(row["contracts_count"]),
               arabic.days(row["rented_days"])),
            "إجمالي الإيرادات: %s" % money.format_amount(row["total_revenue"], self._symbol),
            "إجمالي المصروفات: %s" % money.format_amount(row["total_expenses"], self._symbol),
            "صافي الربح التشغيلي: %s" % money.format_amount(row["net_profit"], self._symbol),
        ]

        if row["recovery_ratio"] is not None:
            lines.append("استرداد رأس المال: %s٪" % row["recovery_ratio"])
            if row["remaining_to_recover"]:
                lines.append(
                    "المتبقّي لاسترداد ثمن الشراء: %s"
                    % money.format_amount(row["remaining_to_recover"], self._symbol)
                )
            if row["months_to_payback"]:
                lines.append(
                    "بمعدّل أدائها الحالي تستردّ ما تبقّى خلال %s تقريباً"
                    % arabic.months(row["months_to_payback"])
                )
        else:
            lines.append(
                "لا تُحسب نسبة الاسترداد: تكلفة شراء السيارة غير مسجَّلة. "
                "أضِفها من شاشة السيارات ← تعديل."
            )

        if row["profit_status"] == profitability.STATUS_MONEY_PIT:
            lines.append(
                "\n⚠ تكاليف هذه السيارة تجاوزت ما أنتجته. راجع دفتر تكاليفها "
                "أدناه قبل قرار الإبقاء أو البيع."
            )

        return "\n".join(lines)

    def refresh(self):
        try:
            self._symbol = settings_repo.base_currency()["symbol"]

            summary = profitability.fleet_summary()
            self.card_fleet.set_value(
                summary["vehicles_count"],
                "منها %s بتكلفة شراء مسجَّلة" % arabic.vehicles(summary["priced_count"]),
            )
            self.card_invested.set_value(
                money.format_amount(summary["invested"], self._symbol),
                "استُرد منه %s٪" % summary["recovery_ratio"]
                if summary["recovery_ratio"] is not None else "لم تُسجَّل تكاليف الشراء",
            )
            self.card_revenue.set_value(
                money.format_amount(summary["total_revenue"], self._symbol)
            )
            self.card_expenses.set_value(
                money.format_amount(summary["total_expenses"], self._symbol)
            )
            self.card_net.set_value(
                money.format_amount(summary["net_profit"], self._symbol)
            )
            self.card_pits.set_value(
                summary["money_pits_count"],
                "خسارة %s" % money.format_amount(
                    abs(summary["money_pits_loss"]), self._symbol
                ) if summary["money_pits_count"] else "لا توجد — الأسطول كلّه يكسب",
            )

            self._rows = profitability.fleet_profitability(
                order=self.order.currentData() or profitability.DEFAULT_ORDER,
                only_money_pits=self.only_pits.isChecked(),
            )
            self.table.fill(self._rows, self._format, cell_color=self._cell_color)
            self._on_select()
        except Exception as error:
            show_error(self, "تعذّر إعداد تقرير الربحية: %s" % error)

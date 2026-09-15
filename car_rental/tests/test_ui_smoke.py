# -*- coding: utf-8 -*-
"""فحص إقلاع الواجهة بلا شاشة (offscreen).

الغرض منه أن يلتقط — قبل أن يصل البرنامج إلى المستخدم — أخطاء الاستيراد،
وأسماء الصفوف الخاطئة في الجداول، وأخطاء الأنماط (QSS)، وأي استثناء يقع
أثناء بناء نافذة أو تحديث صفحة. وهو ما لا تكشفه اختبارات المنطق وحدها.
"""

import datetime

import pytest

from app.core import session

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def gui(qt_app, conn, admin, sample_customer, sample_vehicle):
    """بيانات واقعية + واجهة مهيّأة: عقد مفتوح ودفعة وصيانة ومخالفة."""
    from app.repositories import maintenance_repo
    from app.services import rental_service
    from app.ui import rtl

    rtl.apply(qt_app)

    today = datetime.date.today()
    rental_service.open_contract(
        sample_customer, sample_vehicle,
        today.isoformat(), (today + datetime.timedelta(days=3)).isoformat(),
        deposit_amount=10000, conn=conn,
    )

    second_vehicle = None
    from app.repositories import vehicles_repo

    second_vehicle = vehicles_repo.create(
        {
            "brand": "كيا", "model": "ريو", "year": 2021, "plate_number": "3-77777",
            "color": "أزرق", "daily_rate": 9000, "weekly_rate": 0, "currency_code": "USD",
        },
        conn=conn,
    )
    maintenance_repo.open_maintenance(second_vehicle, "صيانة دورية", conn=conn)
    maintenance_repo.add_violation(
        sample_vehicle, today.isoformat(), "تجاوز السرعة", amount=5000, conn=conn
    )

    return qt_app


def test_rtl_direction_is_applied(gui):
    assert gui.layoutDirection() == Qt.LayoutDirection.RightToLeft


def test_stylesheet_loads(gui):
    assert "sidebar" in gui.styleSheet()


def test_login_window_builds(gui):
    from app.ui.login_window import LoginWindow

    window = LoginWindow()
    window.show()
    gui.processEvents()
    assert window.username is not None
    window.close()


def test_login_window_rejects_empty_credentials(gui):
    from app.ui.login_window import LoginWindow

    window = LoginWindow()
    window.attempt_login()
    assert window.error_label.isVisible() or window.error_label.text()
    window.close()


def test_main_window_builds_for_admin(gui, admin):
    from app.ui.main_window import MainWindow

    window = MainWindow(admin)
    window.show()
    gui.processEvents()

    # المدير في النسخة المتقدّمة يرى كل الصفحات العشر
    assert window.stack.count() == 10
    window.close()


def test_basic_tier_hides_premium_pages(gui, conn, admin):
    """النسخة الأساسية لا تبني صفحات النسخة المتقدّمة أصلاً."""
    from app.core import features
    from app.ui.main_window import MainWindow
    from app.ui.pages.backup_page import BackupPage
    from app.ui.pages.maintenance_page import MaintenancePage
    from app.ui.pages.reports_page import ReportsPage

    features.set_tier(features.TIER_BASIC)
    try:
        window = MainWindow(admin)
        window.show()
        gui.processEvents()

        pages = [type(window.stack.widget(i)) for i in range(window.stack.count())]
        assert ReportsPage not in pages
        assert BackupPage not in pages
        assert MaintenancePage not in pages
        assert window.stack.count() < 10
        window.close()
    finally:
        features.set_tier(features.TIER_PRO)


def test_activation_window_builds(gui, conn):
    from app.ui.activation_window import ActivationWindow

    window = ActivationWindow()
    window.show()
    gui.processEvents()

    assert window.machine_value.text()          # بصمة الجهاز تُعرض للنسخ
    assert window.key_input is not None
    window.close()


def test_subscription_page_reports_state(gui, conn):
    from app.ui.activation_window import SubscriptionPage

    page = SubscriptionPage()
    page.refresh()
    gui.processEvents()

    assert "بصمة هذا الجهاز" in page.status_label.text()
    page.deleteLater()


def test_staff_sees_fewer_pages(gui, conn, admin):
    from app.repositories import users_repo
    from app.ui.main_window import MainWindow
    from app.ui.pages.reports_page import ReportsPage

    users_repo.create("staff1", "موظّف الاستقبال", "Sayara2026", "staff", conn=conn)
    staff = users_repo.authenticate("staff1", "Sayara2026", conn=conn)

    window = MainWindow(staff)
    window.show()
    gui.processEvents()

    assert window.stack.count() == 5
    pages = [type(window.stack.widget(i)) for i in range(window.stack.count())]
    assert ReportsPage not in pages

    window.close()
    session.login(admin)


@pytest.mark.parametrize(
    "page_name",
    ["dashboard_page", "contracts_page", "customers_page", "vehicles_page",
     "maintenance_page", "reports_page", "users_page", "backup_page", "settings_page"],
)
def test_every_page_refreshes_without_error(gui, page_name):
    """كل صفحة تُبنى وتُحدَّث ببيانات حقيقية دون أي استثناء."""
    import importlib

    module = importlib.import_module("app.ui.pages.%s" % page_name)
    page_class = next(
        value for name, value in vars(module).items()
        if name.endswith("Page") and isinstance(value, type)
    )

    page = page_class()
    page.refresh()
    gui.processEvents()
    page.deleteLater()


def test_contract_table_shows_rows(gui):
    from app.ui.pages.contracts_page import ContractsPage

    page = ContractsPage()
    page.refresh()
    assert page.table.model_.rowCount() == 1
    page.deleteLater()


def test_dashboard_quick_search_finds_contract(gui, conn):
    from app.ui.pages.dashboard_page import DashboardPage

    page = DashboardPage()
    page.refresh()
    page.quick_search.setText("5-12345")
    gui.processEvents()

    assert page.search_card.isVisible() or page.search_table.model_.rowCount() == 1
    page.deleteLater()


def test_new_contract_dialog_quotes_live(gui, conn):
    from PyQt6.QtCore import QDate

    from app.ui.pages.contracts_page import NewContractDialog

    dialog = NewContractDialog()
    # سيارة واحدة فقط ما زالت متاحة (الأخرى مؤجَّرة والثالثة في الصيانة)
    dialog.end_date.setDate(QDate.currentDate().addDays(7))
    gui.processEvents()

    text = dialog.quote_label.text()
    assert "الإجمالي" in text or "لا توجد سيارات" in text
    dialog.close()


def test_edit_contract_dialog_builds_and_previews(gui, conn):
    from app.repositories import contracts_repo
    from app.ui.pages.contracts_page import EditContractDialog

    contract = contracts_repo.search(status="open", limit=1, conn=conn)[0]
    dialog = EditContractDialog(contract)
    gui.processEvents()

    assert "الإجمالي الجديد" in dialog.preview_label.text()
    assert dialog.vehicle.count() >= 1
    dialog.close()


def test_renew_preset_fills_the_new_contract_dialog(gui, conn):
    from app.repositories import contracts_repo
    from app.ui.pages.contracts_page import NewContractDialog

    contract = contracts_repo.search(status="open", limit=1, conn=conn)[0]
    preset = {
        "customer_id": contract["customer_id"],
        "vehicle_id": contract["vehicle_id"],
        "start_date": contract["expected_end_date"],
        "start_time": contract["start_time"],
        "days": 5,
        "notes": "تجديد للعقد %s" % contract["contract_number"],
    }

    dialog = NewContractDialog(preset=preset)
    gui.processEvents()

    assert dialog.customer.currentData() == contract["customer_id"]
    assert dialog.vehicle.currentData() == contract["vehicle_id"]
    assert dialog.start_date.date().toString("yyyy-MM-dd") == contract["expected_end_date"]
    assert contract["contract_number"] in dialog.notes.toPlainText()
    dialog.close()


def test_rented_vehicle_is_still_bookable_in_the_dialog(gui, conn):
    """السيارة المؤجَّرة اليوم تظهر في قائمة العقد الجديد مع بيان انشغالها."""
    from app.ui.pages.contracts_page import NewContractDialog

    dialog = NewContractDialog()
    gui.processEvents()

    labels = [dialog.vehicle.itemText(i) for i in range(dialog.vehicle.count())]
    assert any("مشغولة حتى" in label for label in labels)
    dialog.close()


def test_close_dialog_offers_hourly_settlement(gui, conn):
    from app.repositories import contracts_repo
    from app.ui.pages.contracts_page import CloseContractDialog

    contract = contracts_repo.search(status="open", limit=1, conn=conn)[0]
    dialog = CloseContractDialog(contract)
    gui.processEvents()

    assert not dialog.hourly.isChecked()          # الافتراضي بالأيام
    daily_preview = dialog.preview.text()

    dialog.hourly.setChecked(True)
    gui.processEvents()
    hourly_preview = dialog.preview.text()

    assert "ساعة" in hourly_preview
    assert hourly_preview != daily_preview
    dialog.close()


def test_customers_page_can_order_by_frequency(gui, conn):
    from app.ui.pages.customers_page import CustomersPage

    page = CustomersPage()
    page.refresh()
    gui.processEvents()

    page.frequent_toggle.setChecked(True)
    page.refresh()
    gui.processEvents()

    assert page.table.model_.rowCount() >= 1
    headers = [page.table.model_.horizontalHeaderItem(i).text()
               for i in range(page.table.model_.columnCount())]
    assert "عدد العقود" in headers
    page.deleteLater()


def test_vehicle_dialog_has_hourly_rate(gui, conn):
    from app.ui.pages.vehicles_page import VehicleDialog

    dialog = VehicleDialog()
    gui.processEvents()
    assert dialog.hourly_rate is not None
    dialog.close()


def test_contract_pdf_is_generated(gui, conn, tmp_path):
    from app.repositories import contracts_repo
    from app.services import contract_pdf

    contract = contracts_repo.search(limit=1, conn=conn)[0]
    output = tmp_path / "contract.pdf"
    path = contract_pdf.export_pdf(contract["id"], output, conn=conn)

    assert output.is_file()
    assert output.stat().st_size > 1000
    # ملف PDF صحيح يبدأ دائماً بهذه البصمة
    assert output.read_bytes()[:4] == b"%PDF"
    assert str(path) == str(output)


def test_contract_html_contains_arabic_details(gui, conn):
    from app.repositories import contracts_repo
    from app.services import contract_pdf

    contract = contracts_repo.search(limit=1, conn=conn)[0]
    html = contract_pdf.build_html(contract["id"], conn=conn)

    assert 'dir="rtl"' in html
    assert "عقد إيجار سيارة" in html
    assert contract["customer_name"] in html
    assert contract["plate_number"] in html
    assert "الشروط والأحكام" in html


def test_csv_export_is_excel_friendly(gui, conn, tmp_path):
    from app.services import reporting

    path = tmp_path / "outstanding.csv"
    reporting.export_outstanding_csv(path, conn=conn)

    raw = path.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"      # علامة BOM يحتاجها Excel للعربية
    assert "رقم العقد" in raw.decode("utf-8-sig")

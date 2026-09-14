# -*- coding: utf-8 -*-
"""التقارير المالية والتشغيلية والتصدير.

كل المبالغ المجمَّعة تُحوَّل إلى **العملة الأساس** باستخدام سعر الصرف المحفوظ
في كل عقد، لا بسعر اليوم؛ فتبقى تقارير الأشهر الماضية ثابتة لا تتغيّر كلّما
عُدِّل سعر الصرف في الإعدادات.
"""

import csv
import datetime

from ..core import db, money, session
from ..repositories import maintenance_repo, settings_repo

_RATE = money.RATE_SCALE


def month_bounds(year=None, month=None):
    """يُرجع (أول الشهر، آخر الشهر) نصّاً بصيغة YYYY-MM-DD."""
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month
    first = datetime.date(year, month, 1)
    last_day = (datetime.date(year + (month == 12), (month % 12) + 1, 1)
                - datetime.timedelta(days=1))
    return first.isoformat(), last_day.isoformat()


def dashboard_summary(conn=None):
    """أرقام لوحة المعلومات: الأسطول والعقود والمال."""
    from ..repositories import contracts_repo, vehicles_repo

    start, end = month_bounds()
    fleet = vehicles_repo.status_counts(conn=conn)
    contracts = contracts_repo.count_by_status(conn=conn)

    month_revenue = db.scalar(
        """SELECT COALESCE(SUM(total_amount * rate_to_base / ?), 0)
             FROM contracts
            WHERE status != 'cancelled' AND start_date BETWEEN ? AND ?""",
        (_RATE, start, end),
        conn=conn,
        default=0,
    )

    month_collected = db.scalar(
        """SELECT COALESCE(SUM(
                    CASE WHEN p.kind = 'refund' THEN -p.amount ELSE p.amount END
                    * c.rate_to_base / ?), 0)
             FROM payments p JOIN contracts c ON c.id = p.contract_id
            WHERE date(p.paid_at) BETWEEN ? AND ?""",
        (_RATE, start, end),
        conn=conn,
        default=0,
    )

    outstanding = db.scalar(
        """SELECT COALESCE(SUM(balance_due * rate_to_base / ?), 0)
             FROM v_contracts_full
            WHERE status != 'cancelled' AND balance_due > 0""",
        (_RATE,),
        conn=conn,
        default=0,
    )

    overdue = db.scalar(
        """SELECT COUNT(*) FROM contracts
            WHERE status = 'open' AND expected_end_date < date('now', 'localtime')""",
        conn=conn,
        default=0,
    )

    occupancy = 0.0
    if fleet["total"]:
        occupancy = round(100.0 * fleet["rented"] / fleet["total"], 1)

    return {
        "fleet": fleet,
        "contracts": contracts,
        "month_revenue": int(month_revenue),
        "month_collected": int(month_collected),
        "outstanding": int(outstanding),
        "overdue_count": int(overdue),
        "occupancy": occupancy,
        "customers": db.scalar("SELECT COUNT(*) FROM customers", conn=conn, default=0),
        "base_currency": settings_repo.base_currency(conn=conn)["symbol"],
        "period": (start, end),
    }


def monthly_revenue(months=12, conn=None):
    """إيراد كل شهر خلال آخر ``months`` شهراً — يغذّي مخطّط لوحة المعلومات."""
    return db.query(
        """SELECT strftime('%Y-%m', start_date) AS month,
                  COUNT(*)                                        AS contracts,
                  COALESCE(SUM(total_amount * rate_to_base / ?), 0) AS revenue
             FROM contracts
            WHERE status != 'cancelled'
              AND start_date >= date('now', 'localtime', ?)
            GROUP BY month ORDER BY month""",
        (_RATE, "-%d months" % int(months)),
        conn=conn,
    )


def revenue_report(start_date, end_date, conn=None):
    """تقرير إيرادات فترة: العقود والمقبوض والمتبقّي ومصاريف الصيانة."""
    contracted = db.scalar(
        """SELECT COALESCE(SUM(total_amount * rate_to_base / ?), 0)
             FROM contracts
            WHERE status != 'cancelled' AND start_date BETWEEN ? AND ?""",
        (_RATE, start_date, end_date),
        conn=conn,
        default=0,
    )

    collected = db.scalar(
        """SELECT COALESCE(SUM(
                    CASE WHEN p.kind = 'refund' THEN -p.amount ELSE p.amount END
                    * c.rate_to_base / ?), 0)
             FROM payments p JOIN contracts c ON c.id = p.contract_id
            WHERE date(p.paid_at) BETWEEN ? AND ?""",
        (_RATE, start_date, end_date),
        conn=conn,
        default=0,
    )

    contracts_count = db.scalar(
        """SELECT COUNT(*) FROM contracts
            WHERE status != 'cancelled' AND start_date BETWEEN ? AND ?""",
        (start_date, end_date),
        conn=conn,
        default=0,
    )

    maintenance = maintenance_repo.maintenance_cost_total(start_date, end_date, conn=conn)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "contracts_count": int(contracts_count),
        "contracted": int(contracted),
        "collected": int(collected),
        "maintenance_cost": int(maintenance),
        "net": int(collected) - int(maintenance),
        "outstanding": int(contracted) - int(collected),
    }


def top_vehicles(start_date, end_date, limit=10, conn=None):
    """أكثر السيارات تأجيراً وإيراداً في فترة."""
    return db.query(
        """SELECT v.plate_number,
                  v.brand || ' ' || v.model                         AS vehicle_title,
                  COUNT(c.id)                                       AS contracts,
                  COALESCE(SUM(c.days_count), 0)                    AS days,
                  COALESCE(SUM(c.total_amount * c.rate_to_base / ?), 0) AS revenue
             FROM vehicles v
        LEFT JOIN contracts c ON c.vehicle_id = v.id
                             AND c.status != 'cancelled'
                             AND c.start_date BETWEEN ? AND ?
            GROUP BY v.id
            ORDER BY revenue DESC, contracts DESC
            LIMIT ?""",
        (_RATE, start_date, end_date, limit),
        conn=conn,
    )


def top_customers(start_date, end_date, limit=10, conn=None):
    return db.query(
        """SELECT cu.full_name, cu.phone,
                  COUNT(c.id)                                       AS contracts,
                  COALESCE(SUM(c.total_amount * c.rate_to_base / ?), 0) AS revenue
             FROM customers cu
             JOIN contracts c ON c.customer_id = cu.id
                             AND c.status != 'cancelled'
                             AND c.start_date BETWEEN ? AND ?
            GROUP BY cu.id
            ORDER BY revenue DESC
            LIMIT ?""",
        (_RATE, start_date, end_date, limit),
        conn=conn,
    )


def outstanding_report(conn=None):
    """كشف الديون المستحقّة على العملاء."""
    return db.query(
        """SELECT contract_number, customer_name, customer_phone, plate_number,
                  start_date, expected_end_date, total_amount, paid_amount,
                  balance_due, currency_code, status
             FROM v_contracts_full
            WHERE balance_due > 0 AND status != 'cancelled'
            ORDER BY balance_due DESC""",
        conn=conn,
    )


def fleet_report(conn=None):
    """حالة الأسطول: كل سيارة وعدد عقودها وإيرادها الكلي."""
    return db.query(
        """SELECT v.plate_number, v.brand, v.model, v.year, v.color, v.status,
                  v.daily_rate, v.weekly_rate, v.currency_code, v.odometer,
                  COUNT(c.id)                                       AS contracts,
                  COALESCE(SUM(c.total_amount * c.rate_to_base / ?), 0) AS revenue
             FROM vehicles v
        LEFT JOIN contracts c ON c.vehicle_id = v.id AND c.status != 'cancelled'
            GROUP BY v.id
            ORDER BY v.status, v.brand""",
        (_RATE,),
        conn=conn,
    )


# ---------------------------------------------------------------------------
# التصدير
# ---------------------------------------------------------------------------
def export_rows_to_csv(rows, headers, path, money_columns=()):
    """يصدّر صفوفاً إلى ملف CSV يفتحه Excel العربي بلا تشويه.

    يُكتب الملف بترميز ``utf-8-sig`` (مع علامة BOM) لأن Excel على ويندوز
    يفترض ترميز النظام إن غابت العلامة، فتظهر العربية حروفاً مبعثرة.
    """
    session.require_login()
    path = str(path)

    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([label for _, label in headers])

        for row in rows:
            line = []
            for key, _ in headers:
                value = row[key] if key in row.keys() else ""
                if key in money_columns:
                    value = str(money.to_major(value or 0))
                line.append(value)
            writer.writerow(line)

    return path


def export_outstanding_csv(path, conn=None):
    headers = [
        ("contract_number", "رقم العقد"),
        ("customer_name", "العميل"),
        ("customer_phone", "الهاتف"),
        ("plate_number", "رقم اللوحة"),
        ("start_date", "تاريخ البداية"),
        ("expected_end_date", "تاريخ الانتهاء"),
        ("total_amount", "إجمالي العقد"),
        ("paid_amount", "المدفوع"),
        ("balance_due", "المتبقّي"),
        ("currency_code", "العملة"),
    ]
    return export_rows_to_csv(
        outstanding_report(conn=conn), headers, path,
        money_columns=("total_amount", "paid_amount", "balance_due"),
    )


def export_fleet_csv(path, conn=None):
    headers = [
        ("plate_number", "رقم اللوحة"),
        ("brand", "الماركة"),
        ("model", "الموديل"),
        ("year", "سنة الصنع"),
        ("color", "اللون"),
        ("status", "الحالة"),
        ("daily_rate", "السعر اليومي"),
        ("weekly_rate", "السعر الأسبوعي"),
        ("currency_code", "العملة"),
        ("odometer", "العدّاد"),
        ("contracts", "عدد العقود"),
        ("revenue", "الإيراد الكلي"),
    ]
    return export_rows_to_csv(
        fleet_report(conn=conn), headers, path,
        money_columns=("daily_rate", "weekly_rate", "revenue"),
    )


def export_contracts_csv(path, rows=None, conn=None):
    from ..repositories import contracts_repo

    headers = [
        ("contract_number", "رقم العقد"),
        ("customer_name", "العميل"),
        ("plate_number", "رقم اللوحة"),
        ("start_date", "البداية"),
        ("expected_end_date", "الانتهاء المتوقَّع"),
        ("actual_end_date", "الانتهاء الفعلي"),
        ("days_count", "عدد الأيام"),
        ("total_amount", "الإجمالي"),
        ("paid_amount", "المدفوع"),
        ("balance_due", "المتبقّي"),
        ("currency_code", "العملة"),
        ("status", "حالة العقد"),
        ("payment_status", "حالة الدفع"),
    ]
    rows = rows if rows is not None else contracts_repo.search(limit=100000, conn=conn)
    return export_rows_to_csv(
        rows, headers, path,
        money_columns=("total_amount", "paid_amount", "balance_due"),
    )

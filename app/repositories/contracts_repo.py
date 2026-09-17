# -*- coding: utf-8 -*-
"""مستودع العقود: القراءة والبحث وتوليد أرقام العقود.

عمليات فتح العقد وإغلاقه تعيش في ``services/rental_service.py`` لأنّها منطق
عمل مركّب يمسّ عدّة جداول داخل معاملة واحدة، لا مجرّد قراءة أو كتابة صفّ.
"""

import datetime

from ..core import db


def get(contract_id, conn=None):
    return db.query_one(
        "SELECT * FROM v_contracts_full WHERE id = ?", (contract_id,), conn=conn
    )


def get_raw(contract_id, conn=None):
    return db.query_one("SELECT * FROM contracts WHERE id = ?", (contract_id,), conn=conn)


def get_by_number(contract_number, conn=None):
    return db.query_one(
        "SELECT * FROM v_contracts_full WHERE contract_number = ?",
        ((contract_number or "").strip(),),
        conn=conn,
    )


def search(term=None, status=None, payment_status=None, limit=500, conn=None):
    """بحث موحّد: رقم العقد أو اسم العميل أو رقم اللوحة أو هاتف العميل."""
    clauses, params = [], []

    term = (term or "").strip()
    if term:
        pattern = "%" + term + "%"
        clauses.append(
            "(contract_number LIKE ? OR customer_name LIKE ? OR plate_number LIKE ?"
            " OR customer_phone LIKE ? OR customer_national_id LIKE ?)"
        )
        params.extend([pattern] * 5)

    if status:
        clauses.append("status = ?")
        params.append(status)

    if payment_status:
        clauses.append("payment_status = ?")
        params.append(payment_status)

    sql = "SELECT * FROM v_contracts_full"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    return db.query(sql, params, conn=conn)


def open_contracts(conn=None):
    return db.query(
        "SELECT * FROM v_contracts_full WHERE status = 'open' ORDER BY expected_end_date",
        conn=conn,
    )


def due_today_or_overdue(conn=None):
    """العقود المفتوحة التي حلّ موعد إرجاعها أو تجاوزته — تنبيه لوحة المعلومات."""
    today = datetime.date.today().isoformat()
    return db.query(
        """SELECT * FROM v_contracts_full
            WHERE status = 'open' AND expected_end_date <= ?
            ORDER BY expected_end_date""",
        (today,),
        conn=conn,
    )


def unpaid(conn=None):
    """العقود التي عليها متأخّرات مالية."""
    return db.query(
        """SELECT * FROM v_contracts_full
            WHERE balance_due > 0 AND status != 'cancelled'
            ORDER BY balance_due DESC""",
        conn=conn,
    )


def next_contract_number(conn=None):
    """يولّد رقم العقد التالي بصيغة ``CR-YYYY-NNNN``.

    الترقيم يبدأ من جديد كل سنة. يُستدعى **داخل** معاملة الكتابة، ويحمي
    القيد الفريد على ``contract_number`` من أي تصادم نادر.
    """
    year = datetime.date.today().year
    prefix = "CR-%d-" % year

    last = db.scalar(
        """SELECT contract_number FROM contracts
            WHERE contract_number LIKE ?
            ORDER BY id DESC LIMIT 1""",
        (prefix + "%",),
        conn=conn,
    )

    sequence = 1
    if last:
        try:
            sequence = int(str(last).rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = 1

    return "%s%04d" % (prefix, sequence)


def count_by_status(conn=None):
    rows = db.query("SELECT status, COUNT(*) AS n FROM contracts GROUP BY status", conn=conn)
    counts = {"open": 0, "closed": 0, "cancelled": 0}
    for row in rows:
        counts[row["status"]] = row["n"]
    counts["total"] = sum(counts.values())
    return counts

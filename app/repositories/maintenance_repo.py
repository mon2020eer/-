# -*- coding: utf-8 -*-
"""مستودع الصيانة والمخالفات المرورية."""

from ..core import audit, db, features, session


# ---------------------------------------------------------------------------
# الصيانة
# ---------------------------------------------------------------------------
@features.requires_feature("maintenance")
def open_maintenance(vehicle_id, description, kind="repair", cost=0,
                     currency_code="LYD", workshop=None, odometer=None, conn=None):
    """يفتح سجلّ صيانة وينقل السيارة إلى حالة «في الصيانة».

    يُمنع على سيارة ضمن عقد مفتوح: إدخالها الورشة وهي في يد عميل تناقض
    لا يجوز أن تسمح به المنظومة.
    """
    user = session.require_login()
    if not (description or "").strip():
        raise ValueError("وصف الصيانة مطلوب.")

    vehicle = db.query_one("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,), conn=conn)
    if vehicle is None:
        raise ValueError("السيارة غير موجودة.")
    if vehicle["status"] == "rented":
        raise ValueError("السيارة مؤجَّرة ضمن عقد مفتوح. أغلق العقد أولاً.")

    open_record = db.query_one(
        "SELECT id FROM maintenance_records WHERE vehicle_id = ? AND finished_at IS NULL",
        (vehicle_id,),
        conn=conn,
    )
    if open_record:
        raise ValueError("للسيارة سجلّ صيانة مفتوح بالفعل.")

    with db.transaction(conn) as tx:
        cursor = tx.execute(
            """INSERT INTO maintenance_records (vehicle_id, kind, cost, currency_code,
                                                description, workshop, odometer, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (vehicle_id, kind, int(cost or 0), currency_code, description.strip(),
             workshop, odometer, user.id),
        )
        record_id = cursor.lastrowid
        tx.execute("UPDATE vehicles SET status = 'maintenance' WHERE id = ?", (vehicle_id,))
        audit.log("create", "maintenance", record_id, {"vehicle_id": vehicle_id}, conn=tx)

    return record_id


@features.requires_feature("maintenance")
def close_maintenance(record_id, cost=None, odometer=None, note=None, conn=None):
    """يُنهي الصيانة ويعيد السيارة إلى حالة «متاحة»."""
    session.require_login()

    record = db.query_one(
        "SELECT * FROM maintenance_records WHERE id = ?", (record_id,), conn=conn
    )
    if record is None:
        raise ValueError("سجلّ الصيانة غير موجود.")
    if record["finished_at"]:
        raise ValueError("سجلّ الصيانة مُنهى بالفعل.")

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE maintenance_records
                  SET finished_at = datetime('now', 'localtime'),
                      cost = COALESCE(?, cost),
                      odometer = COALESCE(?, odometer),
                      description = CASE WHEN ? IS NULL THEN description
                                         ELSE description || char(10) || ? END
                WHERE id = ?""",
            (cost, odometer, note, note, record_id),
        )
        tx.execute(
            "UPDATE vehicles SET status = 'available' WHERE id = ? AND status = 'maintenance'",
            (record["vehicle_id"],),
        )
        if odometer is not None:
            tx.execute(
                "UPDATE vehicles SET odometer = ? WHERE id = ? AND ? > odometer",
                (odometer, record["vehicle_id"], odometer),
            )
        audit.log("close", "maintenance", record_id, conn=tx)

    return True


def list_maintenance(vehicle_id=None, only_open=False, limit=500, conn=None):
    clauses, params = [], []
    if vehicle_id:
        clauses.append("m.vehicle_id = ?")
        params.append(vehicle_id)
    if only_open:
        clauses.append("m.finished_at IS NULL")

    sql = """SELECT m.*, v.plate_number, v.brand || ' ' || v.model AS vehicle_title
               FROM maintenance_records m
               JOIN vehicles v ON v.id = m.vehicle_id"""
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)

    return db.query(sql, params, conn=conn)


def maintenance_cost_total(start_date, end_date, conn=None):
    """إجمالي مصاريف الصيانة في فترة، بالعملة الأساس."""
    return db.scalar(
        """SELECT COALESCE(SUM(m.cost * c.rate_to_base / 1000000), 0)
             FROM maintenance_records m
             JOIN currencies c ON c.code = m.currency_code
            WHERE date(m.started_at) BETWEEN ? AND ?""",
        (start_date, end_date),
        conn=conn,
        default=0,
    )


# ---------------------------------------------------------------------------
# المخالفات المرورية
# ---------------------------------------------------------------------------
@features.requires_feature("violations")
def add_violation(vehicle_id, occurred_at, description, amount=0,
                  currency_code="LYD", contract_id=None, reference=None,
                  is_charged_to_customer=1, conn=None):
    """يسجّل مخالفة مرورية.

    إن لم يُحدَّد العقد، تُربط المخالفة تلقائياً بالعقد الذي كانت السيارة
    ضمنه في تاريخ المخالفة — وهو ما يحدّد المسؤول عنها.
    """
    user = session.require_login()
    if not (description or "").strip():
        raise ValueError("وصف المخالفة مطلوب.")

    if contract_id is None:
        match = db.query_one(
            """SELECT id FROM contracts
                WHERE vehicle_id = ? AND status != 'cancelled'
                      AND date(?) >= start_date
                      AND date(?) <= COALESCE(actual_end_date, expected_end_date)
                ORDER BY id DESC LIMIT 1""",
            (vehicle_id, occurred_at, occurred_at),
            conn=conn,
        )
        contract_id = match["id"] if match else None

    with db.transaction(conn) as tx:
        cursor = tx.execute(
            """INSERT INTO violations (vehicle_id, contract_id, occurred_at, amount,
                                       currency_code, description, reference,
                                       is_charged_to_customer, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vehicle_id, contract_id, occurred_at, int(amount or 0), currency_code,
             description.strip(), reference, int(is_charged_to_customer), user.id),
        )
        violation_id = cursor.lastrowid
        audit.log("create", "violation", violation_id, {"vehicle_id": vehicle_id}, conn=tx)

    return violation_id


@features.requires_feature("violations")
def settle_violation(violation_id, conn=None):
    session.require_login()
    with db.transaction(conn) as tx:
        tx.execute("UPDATE violations SET is_settled = 1 WHERE id = ?", (violation_id,))
        audit.log("update", "violation", violation_id, {"settled": True}, conn=tx)
    return True


def list_violations(vehicle_id=None, only_unsettled=False, limit=500, conn=None):
    clauses, params = [], []
    if vehicle_id:
        clauses.append("vi.vehicle_id = ?")
        params.append(vehicle_id)
    if only_unsettled:
        clauses.append("vi.is_settled = 0")

    sql = """SELECT vi.*, v.plate_number, c.contract_number, cu.full_name AS customer_name
               FROM violations vi
               JOIN vehicles v  ON v.id = vi.vehicle_id
          LEFT JOIN contracts c ON c.id = vi.contract_id
          LEFT JOIN customers cu ON cu.id = c.customer_id"""
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY vi.occurred_at DESC LIMIT ?"
    params.append(limit)

    return db.query(sql, params, conn=conn)

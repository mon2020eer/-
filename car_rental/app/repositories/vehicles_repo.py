# -*- coding: utf-8 -*-
"""مستودع السيارات."""

from ..core import audit, db, session
from . import _sql

_FIELDS = (
    "brand",
    "model",
    "year",
    "plate_number",
    "color",
    "daily_rate",
    "weekly_rate",
    "currency_code",
    "odometer",
    "chassis_number",
    "notes",
)


def get(vehicle_id, conn=None):
    return db.query_one("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,), conn=conn)


def get_by_plate(plate_number, conn=None):
    return db.query_one(
        "SELECT * FROM vehicles WHERE plate_number = ? COLLATE NOCASE",
        ((plate_number or "").strip(),),
        conn=conn,
    )


def search(term=None, status=None, limit=500, conn=None):
    """بحث بالسيارة: لوحة، ماركة، موديل — مع ترشيح اختياري بالحالة."""
    clauses, params = [], []

    term = (term or "").strip()
    if term:
        pattern = "%" + term + "%"
        clauses.append(
            "(plate_number LIKE ? OR brand LIKE ? OR model LIKE ? OR color LIKE ?)"
        )
        params.extend([pattern] * 4)

    if status:
        clauses.append("status = ?")
        params.append(status)

    sql = "SELECT * FROM vehicles"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY status, brand, model LIMIT ?"
    params.append(limit)

    return db.query(sql, params, conn=conn)


def list_available(conn=None):
    """السيارات المتاحة للتأجير الآن — تغذّي قائمة إنشاء العقد."""
    return db.query(
        "SELECT * FROM vehicles WHERE status = 'available' ORDER BY brand, model",
        conn=conn,
    )


def status_counts(conn=None):
    """عدّاد لكل حالة، يغذّي بطاقات لوحة المعلومات."""
    rows = db.query("SELECT status, COUNT(*) AS n FROM vehicles GROUP BY status", conn=conn)
    counts = {"available": 0, "rented": 0, "maintenance": 0}
    for row in rows:
        counts[row["status"]] = row["n"]
    counts["total"] = sum(counts.values())
    return counts


def _validate(data, vehicle_id=None, conn=None):
    for field, label in (
        ("brand", "الماركة"),
        ("model", "الموديل"),
        ("plate_number", "رقم اللوحة"),
        ("color", "اللون"),
    ):
        if not (data.get(field) or "").strip():
            raise ValueError("%s مطلوب." % label)

    try:
        year = int(data.get("year") or 0)
    except (TypeError, ValueError):
        raise ValueError("سنة الصنع يجب أن تكون رقماً.")
    if not 1950 <= year <= 2100:
        raise ValueError("سنة الصنع غير منطقية.")

    if int(data.get("daily_rate") or 0) <= 0:
        raise ValueError("السعر اليومي مطلوب ويجب أن يكون أكبر من صفر.")

    duplicate = db.query_one(
        "SELECT id FROM vehicles WHERE plate_number = ? COLLATE NOCASE AND id IS NOT ?",
        (data["plate_number"].strip(), vehicle_id),
        conn=conn,
    )
    if duplicate:
        raise ValueError("يوجد سيارة مسجَّلة بنفس رقم اللوحة.")


def create(data, conn=None):
    session.require_login()
    _validate(data, conn=conn)

    with db.transaction(conn) as tx:
        vehicle_id = _sql.insert("vehicles", data, _FIELDS, tx.execute)
        audit.log("create", "vehicle", vehicle_id, {"plate": data.get("plate_number")}, conn=tx)

    return vehicle_id


def update(vehicle_id, data, conn=None):
    session.require_login()
    if get(vehicle_id, conn=conn) is None:
        raise ValueError("السيارة غير موجودة.")
    _validate(data, vehicle_id=vehicle_id, conn=conn)

    data = dict(data)
    # أعمدة لها قيمة افتراضية ولا تقبل NULL: تُضبط صراحةً عند التعديل
    data["weekly_rate"] = int(data.get("weekly_rate") or 0)
    data["odometer"] = int(data.get("odometer") or 0)

    with db.transaction(conn) as tx:
        _sql.update("vehicles", vehicle_id, data, _FIELDS, tx.execute)
        audit.log("update", "vehicle", vehicle_id, {"plate": data.get("plate_number")}, conn=tx)
    return True


def set_status(vehicle_id, status, conn=None):
    """تغيير حالة السيارة يدوياً.

    لا يُسمح بتغيير حالة سيارة مرتبطة بعقد مفتوح: حالتها يحكمها العقد نفسه،
    وإلّا ظهرت سيارة «متاحة» وهي في يد عميل.
    """
    session.require_login()
    if status not in ("available", "rented", "maintenance"):
        raise ValueError("حالة غير معروفة.")

    open_contract = db.query_one(
        "SELECT contract_number FROM contracts WHERE vehicle_id = ? AND status = 'open'",
        (vehicle_id,),
        conn=conn,
    )
    if open_contract:
        raise ValueError(
            "السيارة مرتبطة بالعقد المفتوح %s. أغلق العقد أولاً."
            % open_contract["contract_number"]
        )

    with db.transaction(conn) as tx:
        tx.execute("UPDATE vehicles SET status = ? WHERE id = ?", (status, vehicle_id))
        audit.log("update", "vehicle", vehicle_id, {"status": status}, conn=tx)
    return True


@session.requires_role("admin")
def delete(vehicle_id, conn=None):
    contracts = db.scalar(
        "SELECT COUNT(*) FROM contracts WHERE vehicle_id = ?", (vehicle_id,),
        conn=conn, default=0,
    )
    if contracts:
        raise ValueError(
            "لا يمكن حذف سيارة لها %d عقد مسجَّل. يمكنك نقلها إلى حالة «الصيانة» بدلاً من ذلك."
            % contracts
        )

    with db.transaction(conn) as tx:
        tx.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
        audit.log("delete", "vehicle", vehicle_id, conn=tx)
    return True


def history(vehicle_id, conn=None):
    """سجلّ عقود السيارة، الأحدث أولاً."""
    return db.query(
        "SELECT * FROM v_contracts_full WHERE vehicle_id = ? ORDER BY id DESC",
        (vehicle_id,),
        conn=conn,
    )

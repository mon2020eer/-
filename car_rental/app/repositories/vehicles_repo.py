# -*- coding: utf-8 -*-
"""مستودع السيارات."""

from ..core import audit, db, features, session
from . import _sql

_FIELDS = (
    "brand",
    "model",
    "year",
    "plate_number",
    "color",
    "daily_rate",
    "weekly_rate",
    "hourly_rate",
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


def list_bookable(conn=None):
    """السيارات القابلة للحجز: كل ما ليس في الصيانة.

    السيارة المؤجَّرة اليوم تبقى قابلة للحجز **لفترة لاحقة**، وهو جوهر عمل مكتب
    محدود عدد السيارات. يُرفق مع كل سيارة تاريخ تحرّرها إن كانت مشغولة الآن.
    """
    return db.query(
        """SELECT v.*,
                  (SELECT MAX(COALESCE(c.actual_end_date, c.expected_end_date))
                     FROM contracts c
                    WHERE c.vehicle_id = v.id AND c.status = 'open') AS busy_until
             FROM vehicles v
            WHERE v.status != 'maintenance'
            ORDER BY v.status, v.brand, v.model""",
        conn=conn,
    )


def is_period_free(vehicle_id, start_date, end_date, exclude_contract_id=None, conn=None):
    """يُرجع العقد المتعارض مع الفترة المطلوبة، أو ``None`` إن كانت حرّة.

    الفترة نصف مفتوحة [البداية، النهاية)، فيوم التسليم يصلح بدايةً لعقد تالٍ.
    العقود الملغاة لا تحجز شيئاً.

    هذا الفحص نسخة تطبيقية من المشغّل ``trg_contracts_no_overlap_insert`` — غرضه
    إعطاء رسالة عربية مفهومة تسمّي العقد المتعارض، لا الاستعاضة عن ضمانة المحرّك.
    """
    return db.query_one(
        """SELECT c.id, c.contract_number, c.start_date,
                  COALESCE(c.actual_end_date, c.expected_end_date) AS end_date,
                  cu.full_name AS customer_name
             FROM contracts c
             JOIN customers cu ON cu.id = c.customer_id
            WHERE c.vehicle_id = ?
              AND c.status != 'cancelled'
              AND c.id IS NOT ?
              AND c.start_date < MAX(?, date(?, '+1 day'))
              AND ? < MAX(COALESCE(c.actual_end_date, c.expected_end_date),
                          date(c.start_date, '+1 day'))
            ORDER BY c.start_date LIMIT 1""",
        (vehicle_id, exclude_contract_id, end_date, start_date, start_date),
        conn=conn,
    )


def upcoming_reservations(vehicle_id, conn=None):
    """الحجوزات القادمة للسيارة: عقود مفتوحة لم يبدأ سريانها بعد."""
    return db.query(
        """SELECT c.contract_number, c.start_date, c.expected_end_date,
                  cu.full_name AS customer_name
             FROM contracts c
             JOIN customers cu ON cu.id = c.customer_id
            WHERE c.vehicle_id = ? AND c.status = 'open'
              AND c.start_date > date('now', 'localtime')
            ORDER BY c.start_date""",
        (vehicle_id,),
        conn=conn,
    )


def sync_status(vehicle_id, conn=None):
    """يشتقّ حالة السيارة من واقع سجلّاتها ويحدّثها، ويُرجع الحالة الجديدة.

    الحالة لم تعد تُضبط يدوياً عند كل عملية، لأن السيارة قد تحمل عدّة عقود
    (جارياً ومحجوزات قادمة) فتصير الحالة نتيجةً لا إدخالاً:

        صيانة مفتوحة            ← maintenance
        عقد مفتوح يشمل اليوم    ← rented
        غير ذلك                 ← available   (ولو كانت محجوزة لتاريخ قادم)
    """
    in_maintenance = db.query_one(
        "SELECT 1 FROM maintenance_records WHERE vehicle_id = ? AND finished_at IS NULL",
        (vehicle_id,),
        conn=conn,
    )
    if in_maintenance:
        status = "maintenance"
    else:
        active = db.query_one(
            """SELECT 1 FROM contracts
                WHERE vehicle_id = ? AND status = 'open'
                  AND start_date <= date('now', 'localtime')
                  AND date('now', 'localtime')
                      <= COALESCE(actual_end_date, expected_end_date)""",
            (vehicle_id,),
            conn=conn,
        )
        status = "rented" if active else "available"

    db.execute("UPDATE vehicles SET status = ? WHERE id = ?", (status, vehicle_id), conn=conn)
    return status


def sync_all_statuses(conn=None):
    """يزامن حالات كل السيارات — يُستدعى عند إقلاع التطبيق.

    ضروري لأن مرور الوقت وحده يغيّر الحقيقة: حجز الغد يصير إيجار اليوم، وعقد
    انتهى أمس يترك سيارته متاحة، والتطبيق قد يكون مغلقاً حين يقع ذلك.
    """
    changed = 0
    for row in db.query("SELECT id, status FROM vehicles", conn=conn):
        if sync_status(row["id"], conn=conn) != row["status"]:
            changed += 1
    return changed


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
    features.require("vehicles")

    # حدّ النسخة الأساسية: يُفحص هنا لا في الواجهة، فلا يُتجاوز بأي طريق
    limit = features.vehicle_limit()
    if limit:
        current = db.scalar("SELECT COUNT(*) FROM vehicles", conn=conn, default=0)
        if current >= limit:
            raise features.FeatureLocked(
                "بلغت حدّ النسخة الأساسية (%d سيارة).\n"
                "للترقية إلى النسخة المتقدّمة راجع مزوّد البرنامج." % limit
            )

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

    لا يُسمح بتغييرها وهي ضمن عقد **سارٍ اليوم**: حالتها يحكمها العقد نفسه،
    وإلّا ظهرت سيارة «متاحة» وهي في يد عميل. أمّا الحجوزات القادمة فلا تمنع
    شيئاً لأنّها لم تبدأ بعد.
    """
    session.require_login()
    if status not in ("available", "rented", "maintenance"):
        raise ValueError("حالة غير معروفة.")

    open_contract = db.query_one(
        """SELECT contract_number FROM contracts
            WHERE vehicle_id = ? AND status = 'open'
              AND start_date <= date('now', 'localtime')
              AND date('now', 'localtime')
                  <= COALESCE(actual_end_date, expected_end_date)""",
        (vehicle_id,),
        conn=conn,
    )
    if open_contract:
        raise ValueError(
            "السيارة مرتبطة بالعقد الجاري %s. أنهِ العقد أولاً."
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

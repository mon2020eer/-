# -*- coding: utf-8 -*-
"""مستودع العملاء ومرفقاتهم."""

import pathlib
import shutil
import uuid

from .. import config
from ..core import audit, db, session
from . import _sql

_FIELDS = (
    "full_name",
    "phone",
    "national_id",
    "license_number",
    "license_expiry",
    "nationality",
    "address",
    "notes",
    "is_blacklisted",
)


def get(customer_id, conn=None):
    return db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,), conn=conn)


def search(term=None, limit=500, conn=None):
    """بحث سريع بالاسم أو الهاتف أو الرقم الوطني.

    يُستخدم ``LIKE`` بأنماط على الطرفين: عدد العملاء في مكتب واحد لا يبلغ
    الحجم الذي يستدعي فهرسة نصية كاملة (FTS)، وبساطة الاستعلام أَولى.
    """
    term = (term or "").strip()
    if not term:
        return db.query(
            "SELECT * FROM customers ORDER BY full_name LIMIT ?", (limit,), conn=conn
        )

    pattern = "%" + term + "%"
    return db.query(
        """SELECT * FROM customers
            WHERE full_name LIKE ? OR phone LIKE ? OR national_id LIKE ?
                  OR license_number LIKE ?
            ORDER BY full_name LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit),
        conn=conn,
    )


def _validate(data, customer_id=None, conn=None):
    if not (data.get("full_name") or "").strip():
        raise ValueError("اسم العميل مطلوب.")
    if not (data.get("phone") or "").strip():
        raise ValueError("رقم الهاتف مطلوب.")
    if not (data.get("national_id") or "").strip():
        raise ValueError("رقم الجواز أو الرقم الوطني مطلوب.")
    if not (data.get("license_number") or "").strip():
        raise ValueError("رقم رخصة القيادة مطلوب.")

    duplicate = db.query_one(
        "SELECT id FROM customers WHERE national_id = ? AND id IS NOT ?",
        (data["national_id"].strip(), customer_id),
        conn=conn,
    )
    if duplicate:
        raise ValueError("يوجد عميل مسجَّل بنفس رقم الجواز/الرقم الوطني.")


def create(data, conn=None):
    session.require_login()
    _validate(data, conn=conn)

    with db.transaction(conn) as tx:
        customer_id = _sql.insert("customers", data, _FIELDS, tx.execute)
        audit.log("create", "customer", customer_id, {"name": data.get("full_name")}, conn=tx)

    return customer_id


def update(customer_id, data, conn=None):
    session.require_login()
    if get(customer_id, conn=conn) is None:
        raise ValueError("العميل غير موجود.")
    _validate(data, customer_id=customer_id, conn=conn)

    data = dict(data)
    data["is_blacklisted"] = int(data.get("is_blacklisted") or 0)

    with db.transaction(conn) as tx:
        _sql.update("customers", customer_id, data, _FIELDS, tx.execute)
        audit.log("update", "customer", customer_id, {"name": data.get("full_name")}, conn=tx)
    return True


@session.requires_role("admin")
def delete(customer_id, conn=None):
    """حذف عميل — يُمنع إن كان مرتبطاً بأي عقد، حفاظاً على تكامل السجلّات."""
    contracts = db.scalar(
        "SELECT COUNT(*) FROM contracts WHERE customer_id = ?", (customer_id,),
        conn=conn, default=0,
    )
    if contracts:
        raise ValueError(
            "لا يمكن حذف عميل له %d عقد مسجَّل. يمكنك إدراجه في القائمة السوداء بدلاً من ذلك."
            % contracts
        )

    with db.transaction(conn) as tx:
        tx.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        audit.log("delete", "customer", customer_id, conn=tx)
    return True


def contracts_of(customer_id, conn=None):
    return db.query(
        "SELECT * FROM v_contracts_full WHERE customer_id = ? ORDER BY id DESC",
        (customer_id,),
        conn=conn,
    )


def outstanding_balance(customer_id, conn=None):
    """إجمالي ما على العميل من متأخّرات، محوَّلاً إلى العملة الأساس."""
    return db.scalar(
        """SELECT COALESCE(SUM(balance_due * rate_to_base / 1000000), 0)
             FROM v_contracts_full
            WHERE customer_id = ? AND status != 'cancelled' AND balance_due > 0""",
        (customer_id,),
        conn=conn,
        default=0,
    )


# ---------------------------------------------------------------------------
# المرفقات: تُنسخ إلى مجلد بيانات التطبيق فلا تضيع إن نُقل الملف الأصلي
# ---------------------------------------------------------------------------
def add_attachment(customer_id, source_path, kind="other", note=None, conn=None):
    session.require_login()
    source = pathlib.Path(source_path)
    if not source.is_file():
        raise ValueError("الملف المحدَّد غير موجود.")

    config.ensure_directories()
    target_dir = config.ATTACHMENTS_DIR / str(customer_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    # اسم فريد يمنع تصادم ملفين بنفس الاسم
    target = target_dir / ("%s_%s" % (uuid.uuid4().hex[:8], source.name))
    shutil.copy2(str(source), str(target))

    with db.transaction(conn) as tx:
        cursor = tx.execute(
            """INSERT INTO customer_attachments (customer_id, file_name, stored_path, kind, note)
               VALUES (?, ?, ?, ?, ?)""",
            (customer_id, source.name, str(target), kind, note),
        )
        attachment_id = cursor.lastrowid
        audit.log("create", "customer", customer_id, {"attachment": source.name}, conn=tx)

    return attachment_id


def attachments_of(customer_id, conn=None):
    return db.query(
        "SELECT * FROM customer_attachments WHERE customer_id = ? ORDER BY id DESC",
        (customer_id,),
        conn=conn,
    )


def delete_attachment(attachment_id, conn=None):
    session.require_login()
    row = db.query_one(
        "SELECT * FROM customer_attachments WHERE id = ?", (attachment_id,), conn=conn
    )
    if row is None:
        return False

    with db.transaction(conn) as tx:
        tx.execute("DELETE FROM customer_attachments WHERE id = ?", (attachment_id,))

    # حذف الملف بعد نجاح المعاملة؛ فشل الحذف لا يُبطل العملية
    try:
        pathlib.Path(row["stored_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return True

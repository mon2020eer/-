# -*- coding: utf-8 -*-
"""مستودع العملاء ومرفقاتهم."""

import pathlib
import shutil
import uuid

from .. import config
from ..core import audit, db, features, session
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


def search(term=None, limit=500, order_by="name", incomplete_only=False, conn=None):
    """بحث سريع بالاسم أو الهاتف أو الرقم الوطني أو رقم الرخصة.

    يُستخدم ``LIKE`` بأنماط على الطرفين: عدد العملاء في مكتب واحد لا يبلغ
    الحجم الذي يستدعي فهرسة نصية كاملة (FTS)، وبساطة الاستعلام أَولى.

    يُرفق مع كل عميل عدد عقوده وتاريخ آخر تعامل، لأن الموظّف يحتاج أن يعرف
    من هو العميل المتكرّر قبل أن يفتح ملفّه.

    ``order_by="frequent"`` يرتّب بالأكثر تعاملاً ثم بالأحدث — وهو الترتيب
    الذي يضع العملاء الذين يترددون على المكتب في أعلى القائمة.

    ``incomplete_only=True`` يرشّح الملفّات الناقصة **في الاستعلام** قبل
    ``LIMIT``: ترشيحُها بعده كان يُسقط كل ناقصٍ خارج أول خمسمئة، فتعرض شاشة
    «الناقصة» قائمةً أقصر من الحقيقة ويطمئنّ المكتب إلى اكتمالٍ لا وجود له.
    """
    term = (term or "").strip()
    clauses, params = [], []

    if term:
        pattern = "%" + term + "%"
        clauses.append(
            "(c.full_name LIKE ? OR c.phone LIKE ? OR c.national_id LIKE ?"
            " OR c.license_number LIKE ?)"
        )
        params.extend([pattern] * 4)

    if incomplete_only:
        clauses.append(_INCOMPLETE_SQL)

    order = (
        "contracts_count DESC, last_contract_date DESC, c.full_name"
        if order_by == "frequent"
        else "c.full_name"
    )

    sql = """
        SELECT c.*,
               COUNT(ct.id)                                   AS contracts_count,
               MAX(ct.start_date)                             AS last_contract_date,
               COALESCE(SUM(CASE WHEN ct.status != 'cancelled'
                                 THEN ct.total_amount * ct.rate_to_base / 1000000
                                 ELSE 0 END), 0)              AS total_spent
          FROM customers c
     LEFT JOIN contracts ct ON ct.customer_id = c.id AND ct.status != 'cancelled'
    """
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " GROUP BY c.id ORDER BY %s LIMIT ?" % order
    params.append(limit)

    return db.query(sql, params, conn=conn)


def frequent(limit=20, min_contracts=2, conn=None):
    """العملاء المتكرّرون: من له عقدان فأكثر، مرتَّبين بالأكثر تعاملاً."""
    return db.query(
        """SELECT c.*,
                  COUNT(ct.id)       AS contracts_count,
                  MAX(ct.start_date) AS last_contract_date
             FROM customers c
             JOIN contracts ct ON ct.customer_id = c.id AND ct.status != 'cancelled'
            GROUP BY c.id
           HAVING contracts_count >= ?
            ORDER BY contracts_count DESC, last_contract_date DESC
            LIMIT ?""",
        (int(min_contracts), int(limit)),
        conn=conn,
    )


# الحقول التي يكتمل بها ملفّ العميل. ناقصُها يعمل في المنظومة لكنه مُعلَّم.
REQUIRED_FOR_COMPLETE = {
    "phone": "رقم الهاتف",
    "national_id": "رقم الجواز أو الرقم الوطني",
    "license_number": "رقم رخصة القيادة",
}

# الشرط نفسه بلغة SQL، مشتقٌّ من القاموس أعلاه فلا يفترقان: إضافة حقل إلزامي
# واحد كانت ستجعل شاشةَ «الناقصة» وعدّادَ اللوحة يقيسان شيئين مختلفين.
_INCOMPLETE_SQL = "(%s)" % " OR ".join(
    "c.%s IS NULL OR TRIM(c.%s) = ''" % (field, field)
    for field in REQUIRED_FOR_COMPLETE
)


def missing_fields(row):
    """أسماء الحقول الناقصة في ملفّ عميل، بالعربية وبترتيب ثابت."""
    return [label for key, label in REQUIRED_FOR_COMPLETE.items()
            if not (row[key] if key in row.keys() else None)]


def is_incomplete(row):
    """هل ملفّ العميل ناقص؟ محسوبة لا مخزَّنة، فلا تتناقض مع البيانات."""
    return bool(missing_fields(row))


def count_incomplete(conn=None):
    """عدد الملفّات الناقصة — بلا سقف ولا ترشيح بعد ``LIMIT``.

    العدّ في SQL لا في بايثون: عدُّ صفوفٍ جُلبت بسقفٍ يُخرج رقماً أصغر من
    الحقيقة حين يتجاوز عدد العملاء ذلك السقف، ورقمُ تحذيرٍ ناقص أسوأ من لا رقم.
    """
    return db.scalar(
        "SELECT COUNT(*) FROM customers c WHERE %s" % _INCOMPLETE_SQL,
        conn=conn, default=0,
    )


# الحقول النصّية التي تُقصّ مسافاتها قبل الفحص والحفظ معاً. المعرّفات منها
# خاصّةً: فحصٌ يقصّ وحفظٌ لا يقصّ يجعل « 119876 » و«119876» عميلين لشخص واحد،
# فيتفرّق سجلّه بين ملفّين ولا يُكتشف الخطأ إلّا بعد فوات وقته.
_TRIMMED_FIELDS = ("full_name", "national_id", "license_number", "phone",
                   "nationality", "address")


def normalize(data):
    """نسخة من بيانات العميل بحقولها النصّية مقصوصة المسافات."""
    clean = dict(data)
    for field in _TRIMMED_FIELDS:
        if field in clean:
            value = clean[field]
            clean[field] = value.strip() or None if isinstance(value, str) else value
    return clean


def _validate(data, customer_id=None, conn=None):
    """يتحقّق من الحدّ الأدنى فقط.

    الاسم وحده إلزامي عمداً: المكتب يستقبل زبوناً واقفاً أمامه فيكتب اسمه ويفتح
    العقد، ثم يُكمل وثائقه. ومنعُه من العمل حتى يُملأ كل حقل يدفعه إلى كتابة
    أرقام مُختلَقة — وبيانات كاذبة أسوأ من بيانات ناقصة معلومة النقص.
    """
    if not (data.get("full_name") or "").strip():
        raise ValueError("اسم العميل مطلوب.")

    national_id = (data.get("national_id") or "").strip()
    if not national_id:
        return

    duplicate = db.query_one(
        "SELECT id FROM customers WHERE national_id = ? AND id IS NOT ?",
        (national_id, customer_id),
        conn=conn,
    )
    if duplicate:
        raise ValueError("يوجد عميل مسجَّل بنفس رقم الجواز/الرقم الوطني.")


def create(data, conn=None):
    session.require_login()
    features.require("customers")
    data = normalize(data)
    _validate(data, conn=conn)

    with db.transaction(conn) as tx:
        customer_id = _sql.insert("customers", data, _FIELDS, tx.execute)
        audit.log("create", "customer", customer_id, {"name": data.get("full_name")}, conn=tx)

    return customer_id


def update(customer_id, data, conn=None):
    session.require_login()
    if get(customer_id, conn=conn) is None:
        raise ValueError("العميل غير موجود.")
    data = normalize(data)
    _validate(data, customer_id=customer_id, conn=conn)

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

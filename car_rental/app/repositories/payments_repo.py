# -*- coding: utf-8 -*-
"""مستودع الدفعات.

حالة الدفع (مدفوع / عربون / مستحق) **لا تُخزَّن** في جدول العقود، بل تُشتَقّ
من مجموع الدفعات عبر العرض ``v_contract_balance``. وبذلك يستحيل أن يظهر عقد
«مدفوع» بلا دفعات مسجَّلة.
"""

from ..core import audit, db, features, session


def of_contract(contract_id, conn=None):
    return db.query(
        "SELECT * FROM payments WHERE contract_id = ? ORDER BY paid_at, id",
        (contract_id,),
        conn=conn,
    )


def balance(contract_id, conn=None):
    return db.query_one(
        "SELECT * FROM v_contract_balance WHERE contract_id = ?", (contract_id,), conn=conn
    )


def add(contract_id, amount, method="cash", kind="payment", note=None,
        reference=None, paid_at=None, conn=None):
    """يسجّل دفعة على عقد.

    يُمنع تجاوز قيمة العقد: الدفع الزائد غالباً خطأ إدخال، ومعالجته الصحيحة
    تكون بتعديل قيمة العقد أو بتسجيل مبلغ مُعاد (kind='refund').
    """
    user = session.require_login()
    features.require("payments")

    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("قيمة الدفعة يجب أن تكون أكبر من صفر.")
    if method not in ("cash", "bank", "card", "other"):
        raise ValueError("طريقة الدفع غير معروفة.")
    if kind not in ("deposit", "payment", "refund"):
        raise ValueError("نوع الدفعة غير معروف.")

    contract = db.query_one(
        "SELECT status FROM contracts WHERE id = ?", (contract_id,), conn=conn
    )
    if contract is None:
        raise ValueError("العقد غير موجود.")
    if contract["status"] == "cancelled":
        raise ValueError("لا يمكن تسجيل دفعات على عقد مُلغى.")

    current = balance(contract_id, conn=conn)
    if kind != "refund" and current and amount > int(current["balance_due"]):
        raise ValueError(
            "قيمة الدفعة تتجاوز المتبقّي على العقد. المتبقّي الحالي أقلّ من المبلغ المُدخَل."
        )
    if kind == "refund" and current and amount > int(current["paid_amount"]):
        raise ValueError("قيمة المبلغ المُعاد تتجاوز ما دفعه العميل فعلاً.")

    with db.transaction(conn) as tx:
        cursor = tx.execute(
            """INSERT INTO payments (contract_id, amount, method, kind, reference,
                                     note, recorded_by, paid_at)
               VALUES (?, ?, ?, ?, ?, ?, ?,
                       COALESCE(?, datetime('now', 'localtime')))""",
            (contract_id, amount, method, kind, reference, note, user.id, paid_at),
        )
        payment_id = cursor.lastrowid
        audit.log(
            "payment", "contract", contract_id,
            {"amount": amount, "method": method, "kind": kind}, conn=tx,
        )

    return payment_id


@session.requires_role("admin")
def delete(payment_id, conn=None):
    """حذف دفعة مسجَّلة خطأً — للمدير فقط ومع تسجيلها في سجلّ التدقيق."""
    row = db.query_one("SELECT * FROM payments WHERE id = ?", (payment_id,), conn=conn)
    if row is None:
        return False

    with db.transaction(conn) as tx:
        tx.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
        audit.log(
            "delete", "payment", payment_id,
            {"contract_id": row["contract_id"], "amount": row["amount"]}, conn=tx,
        )
    return True


def totals_between(start_date, end_date, conn=None):
    """إجمالي المقبوضات في فترة، محوَّلاً إلى العملة الأساس بسعر صرف كل عقد."""
    return db.scalar(
        """SELECT COALESCE(SUM(
                     CASE WHEN p.kind = 'refund' THEN -p.amount ELSE p.amount END
                     * c.rate_to_base / 1000000), 0)
             FROM payments p
             JOIN contracts c ON c.id = p.contract_id
            WHERE date(p.paid_at) BETWEEN ? AND ?""",
        (start_date, end_date),
        conn=conn,
        default=0,
    )

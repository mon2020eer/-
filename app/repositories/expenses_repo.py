# -*- coding: utf-8 -*-
"""مستودع مصروفات السيارات — دفتر التكاليف الذي تقوم عليه وحدة تحليل الربحية.

**لماذا دفتر مستقلّ عن سجلّ الصيانة؟** لأن سجلّ الصيانة يصف حدثاً تشغيلياً
يوقف السيارة عن العمل وينقلها إلى حالة «في الصيانة»، بينما أكثر ما يُصرف على
سيارة لا يوقفها: إطارات تُبدَّل، وزيت يُغيَّر، ووثيقة تأمين تُجدَّد. وإلزامُ
الموظّف بفتح «سجلّ صيانة» ليسجّل ثمن زيت يعني أحد أمرين: إمّا أن تُعطَّل سيارة
عاملة في الدفاتر، وإمّا ألّا يُسجَّل المصروف أصلاً — وكلاهما يُفسد حساب الربح.

وفي المقابل **لا يُهمَل سجلّ الصيانة في الحساب**: تقرير الربحية يقرأ المصدرين
معاً من العرض ``v_vehicle_expense_ledger`` (انظر ``services/profitability.py``).

كل المبالغ أعداد صحيحة بالوحدة الصغرى، وتُحفظ معها **لقطة سعر الصرف** يوم
الصرف على غرار العقود: تقرير ربحية سيارةٍ عمرها سنتان لا يجوز أن تتبدّل أرقامه
كلّما عُدِّل سعر صرف في شاشة الإعدادات.
"""

import datetime

from ..core import audit, db, features, session

# أنواع المصروفات المقبولة — يجب أن تطابق قيد CHECK في المخطط حرفاً بحرف
EXPENSE_TYPES = ("maintenance", "tyres", "oil", "insurance", "other")


def _rate_of(currency_code, conn=None):
    """سعر صرف العملة مقابل العملة الأساس **اليوم**، ليُحفظ لقطةً في المصروف."""
    rate = db.scalar(
        "SELECT rate_to_base FROM currencies WHERE code = ?",
        (currency_code,),
        conn=conn,
        default=None,
    )
    if rate is None:
        raise ValueError("العملة غير معرَّفة: %s" % currency_code)
    return int(rate)


def _default_currency(vehicle, conn=None):
    """عملة السيارة نفسها هي الافتراض: بها اشتُريت وبها تُؤجَّر."""
    return vehicle["currency_code"] if vehicle else "LYD"


def _validate(vehicle_id, expense_type, amount, date, conn=None):
    """يتحقّق من المصروف قبل حفظه، ويُرجع صفّ السيارة."""
    vehicle = db.query_one("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,), conn=conn)
    if vehicle is None:
        raise ValueError("السيارة غير موجودة.")

    if expense_type not in EXPENSE_TYPES:
        raise ValueError("نوع مصروف غير معروف.")

    if int(amount or 0) <= 0:
        raise ValueError("قيمة المصروف مطلوبة ويجب أن تكون أكبر من صفر.")

    # التاريخ يُفحص شكلاً ومعنًى: مصروفٌ في المستقبل خطأ إدخال لا واقعة،
    # وتقريرُ ربحيةٍ يحمل تكلفة لم تُصرف بعد يُضلّل قرار البيع أو الإبقاء.
    try:
        entered = datetime.date.fromisoformat(str(date))
    except (TypeError, ValueError):
        raise ValueError("تاريخ المصروف غير صحيح. الصيغة المطلوبة YYYY-MM-DD.")
    if entered > datetime.date.today():
        raise ValueError("لا يمكن تسجيل مصروف بتاريخ لاحق لليوم.")

    return vehicle


@features.requires_feature("profitability")
def add_expense(vehicle_id, expense_type, amount, date=None, notes=None,
                currency_code=None, conn=None):
    """يسجّل مصروفاً على سيارة ويُرجع معرّفه.

    ``amount`` بالوحدة الصغرى (يحوّلها ``money.to_minor`` في الواجهة).
    ``date`` بصيغة YYYY-MM-DD، وافتراضه اليوم.
    """
    user = session.require_login()
    date = date or datetime.date.today().isoformat()

    vehicle = _validate(vehicle_id, expense_type, amount, date, conn=conn)
    currency_code = currency_code or _default_currency(vehicle, conn=conn)
    rate = _rate_of(currency_code, conn=conn)

    with db.transaction(conn) as tx:
        cursor = tx.execute(
            """INSERT INTO vehicle_expenses (vehicle_id, expense_type, amount,
                                             currency_code, rate_to_base, date,
                                             notes, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (vehicle_id, expense_type, int(amount), currency_code, rate, date,
             (notes or "").strip() or None, user.id),
        )
        expense_id = cursor.lastrowid
        audit.log("create", "vehicle_expense", expense_id,
                  {"vehicle_id": vehicle_id, "type": expense_type, "amount": int(amount)},
                  conn=tx)

    return expense_id


@features.requires_feature("profitability")
def update_expense(expense_id, expense_type, amount, date, notes=None,
                   currency_code=None, conn=None):
    """يعدّل مصروفاً مسجَّلاً.

    لقطة سعر الصرف تُعاد بسعر **اليوم** لأن العملة قد تكون تغيّرت في التعديل،
    ولأن المصروف المعدَّل واقعةٌ يُعاد إثباتها لا واقعة قديمة تُنقل كما هي.
    """
    session.require_login()

    current = get(expense_id, conn=conn)
    if current is None:
        raise ValueError("المصروف غير موجود.")

    vehicle = _validate(current["vehicle_id"], expense_type, amount, date, conn=conn)
    currency_code = currency_code or current["currency_code"] or _default_currency(vehicle)
    rate = _rate_of(currency_code, conn=conn)

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE vehicle_expenses
                  SET expense_type = ?, amount = ?, currency_code = ?,
                      rate_to_base = ?, date = ?, notes = ?
                WHERE id = ?""",
            (expense_type, int(amount), currency_code, rate, date,
             (notes or "").strip() or None, expense_id),
        )
        audit.log("update", "vehicle_expense", expense_id,
                  {"vehicle_id": current["vehicle_id"], "amount": int(amount)}, conn=tx)

    return True


@session.requires_role("admin")
def delete_expense(expense_id, conn=None):
    """يحذف مصروفاً — للمدير وحده.

    الحذف مقصور على المدير لأن المصروف رقمٌ يدخل حساب الربح مباشرةً: موظّفٌ
    يمحو تكلفة يجعل سيارةً خاسرة تبدو رابحة، ولا أثر لذلك في الجدول نفسه.
    """
    current = get(expense_id, conn=conn)
    if current is None:
        raise ValueError("المصروف غير موجود.")

    with db.transaction(conn) as tx:
        tx.execute("DELETE FROM vehicle_expenses WHERE id = ?", (expense_id,))
        audit.log("delete", "vehicle_expense", expense_id,
                  {"vehicle_id": current["vehicle_id"], "amount": current["amount"]},
                  conn=tx)
    return True


# ---------------------------------------------------------------------------
# القراءة
# ---------------------------------------------------------------------------
def get(expense_id, conn=None):
    return db.query_one(
        "SELECT * FROM vehicle_expenses WHERE id = ?", (expense_id,), conn=conn
    )


def list_expenses(vehicle_id=None, start_date=None, end_date=None, limit=1000, conn=None):
    """المصروفات المُدخَلة يدوياً — وهي وحدها القابلة للتعديل والحذف."""
    clauses, params = [], []
    if vehicle_id:
        clauses.append("e.vehicle_id = ?")
        params.append(vehicle_id)
    if start_date:
        clauses.append("e.date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("e.date <= ?")
        params.append(end_date)

    sql = """SELECT e.*, v.plate_number, v.brand || ' ' || v.model AS vehicle_title
               FROM vehicle_expenses e
               JOIN vehicles v ON v.id = e.vehicle_id"""
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY e.date DESC, e.id DESC LIMIT ?"
    params.append(limit)

    return db.query(sql, params, conn=conn)


def list_ledger(vehicle_id, limit=1000, conn=None):
    """دفتر تكاليف السيارة موحّداً: المصروفات اليدوية + تكاليف الصيانة.

    هذا ما يُعرض في ملفّ السيارة، لأن صاحب المكتب يسأل «كم صُرف على هذه
    السيارة؟» ولا يعنيه من أي شاشة أُدخل الرقم.
    """
    return db.query(
        """SELECT * FROM v_vehicle_expense_ledger
            WHERE vehicle_id = ?
            ORDER BY expense_date DESC, id DESC
            LIMIT ?""",
        (vehicle_id, limit),
        conn=conn,
    )


def totals_by_type(vehicle_id=None, conn=None):
    """مجموع التكاليف مقسوماً على أنواعها، بالعملة الأساس.

    يجيب السؤال التالي لسؤال «كم صُرف؟»: **في ماذا صُرف؟** — وهو ما يميّز
    سيارةً تلتهم قطع غيار من سيارةٍ ثمّن تأمينها مرتفع.
    """
    sql = """SELECT expense_type,
                    COUNT(*)          AS entries,
                    SUM(amount_base)  AS total
               FROM v_vehicle_expense_ledger"""
    params = []
    if vehicle_id:
        sql += " WHERE vehicle_id = ?"
        params.append(vehicle_id)
    sql += " GROUP BY expense_type ORDER BY total DESC"

    return db.query(sql, params, conn=conn)


def total_for_vehicle(vehicle_id, conn=None):
    """إجمالي ما صُرف على سيارة بالعملة الأساس."""
    return int(db.scalar(
        "SELECT COALESCE(SUM(amount_base), 0) FROM v_vehicle_expense_ledger"
        " WHERE vehicle_id = ?",
        (vehicle_id,),
        conn=conn,
        default=0,
    ))


def expenses_total(start_date=None, end_date=None, conn=None):
    """إجمالي مصروفات الأسطول في فترة (أو منذ البداية)، بالعملة الأساس."""
    clauses, params = [], []
    if start_date:
        clauses.append("expense_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("expense_date <= ?")
        params.append(end_date)

    sql = "SELECT COALESCE(SUM(amount_base), 0) FROM v_vehicle_expense_ledger"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    return int(db.scalar(sql, params, conn=conn, default=0))


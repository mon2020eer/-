# -*- coding: utf-8 -*-
"""مستودع الإعدادات والعملات."""

from ..core import audit, db, money, session


# ---------------------------------------------------------------------------
# الإعدادات (مفتاح/قيمة)
# ---------------------------------------------------------------------------
def get(key, default=None, conn=None):
    value = db.scalar("SELECT value FROM app_settings WHERE key = ?", (key,), conn=conn)
    return default if value is None else value


def get_int(key, default=0, conn=None):
    try:
        return int(get(key, default, conn=conn))
    except (TypeError, ValueError):
        return default


def get_bool(key, default=False, conn=None):
    value = get(key, None, conn=conn)
    if value is None:
        return default
    return str(value).strip() in ("1", "true", "True", "yes")


def all_settings(conn=None):
    return {row["key"]: row["value"] for row in db.query("SELECT * FROM app_settings", conn=conn)}


def set_value(key, value, conn=None):
    """يحفظ إعداداً واحداً. لا يكتب في سجلّ التدقيق (تفعله ``set_many``)."""
    db.execute(
        """INSERT INTO app_settings (key, value, updated_at)
           VALUES (?, ?, datetime('now', 'localtime'))
           ON CONFLICT (key) DO UPDATE
               SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, None if value is None else str(value)),
        conn=conn,
    )
    return True


def set_many(values, conn=None):
    """يحفظ مجموعة إعدادات داخل معاملة واحدة."""
    session.require_login()
    with db.transaction(conn) as tx:
        for key, value in values.items():
            set_value(key, value, conn=tx)
        audit.log("update", "settings", details={"keys": sorted(values)}, conn=tx)
    return True


# ---------------------------------------------------------------------------
# العملات
# ---------------------------------------------------------------------------
def list_currencies(conn=None):
    return db.query("SELECT * FROM currencies ORDER BY is_base DESC, code", conn=conn)


def get_currency(code, conn=None):
    return db.query_one("SELECT * FROM currencies WHERE code = ?", (code,), conn=conn)


def base_currency(conn=None):
    row = db.query_one("SELECT * FROM currencies WHERE is_base = 1 LIMIT 1", conn=conn)
    return row or get_currency("LYD", conn=conn)


def symbol_of(code, conn=None):
    row = get_currency(code, conn=conn)
    return row["symbol"] if row else (code or "")


def format_amount(minor, code=None, conn=None):
    """ينسّق مبلغاً بعلامة عملته: ``1,250.00 د.ل``."""
    return money.format_amount(minor, symbol_of(code, conn=conn) if code else None)


@session.requires_role("admin")
def set_exchange_rate(code, rate_display, conn=None):
    """يحدّث سعر صرف عملة مقابل العملة الأساس — للمدير فقط.

    لا يمسّ العقود القديمة إطلاقاً: كل عقد يحمل سعر الصرف وقت إنشائه.
    """
    row = get_currency(code, conn=conn)
    if row is None:
        raise ValueError("العملة غير معرَّفة.")
    if row["is_base"]:
        raise ValueError("سعر صرف العملة الأساس ثابت عند 1.")

    stored = money.rate_to_int(rate_display)
    if stored <= 0:
        raise ValueError("سعر الصرف يجب أن يكون أكبر من صفر.")

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE currencies
                  SET rate_to_base = ?, updated_at = datetime('now', 'localtime')
                WHERE code = ?""",
            (stored, code),
        )
        audit.log("update", "settings", details={"currency": code, "rate": str(rate_display)},
                  conn=tx)
    return True


@session.requires_role("admin")
def set_base_currency(code, conn=None):
    """يغيّر العملة الأساس — **قبل أول عقد فقط**.

    عملية نادرة وحسّاسة: أسعار الصرف تُعاد نسبتها إلى العملة الجديدة.

    ويُمنع التغيير بعد وجود عقود، لأن كل عقد يحفظ ``rate_to_base`` وقت إنشائه
    فتبقى أرقام الماضي محسوبةً بالأساس القديم وتُعرض برمز العملة الجديد: يقرأ
    صاحب المكتب «٥٥٠٠٠ دولاراً» عن عقد قيمته ٥٥٠٠٠ ديناراً، ويبني عليه قراره.
    وترحيلُ الأرقام القديمة ليس حلّاً أصدق: سعرُ صرف اليوم ليس سعر يوم العقد،
    فالترحيل يوهم بدقّة لا يملكها. والمنع الصريح أنظف من رقمٍ يكذب بصمت.
    """
    new_base = get_currency(code, conn=conn)
    if new_base is None:
        raise ValueError("العملة غير معرَّفة.")
    if new_base["is_base"]:
        return True

    contracts = db.scalar("SELECT COUNT(*) FROM contracts", conn=conn, default=0)
    if contracts:
        raise ValueError(
            "لا يمكن تغيير العملة الأساس بعد تسجيل عقود (%d عقداً).\n"
            "كل عقد يحفظ سعر صرفه وقت إنشائه، وتغيير الأساس يجعل أرقام "
            "التقارير القديمة تُعرض بعملة غير التي حُسبت بها." % int(contracts)
        )

    factor = int(new_base["rate_to_base"])

    with db.transaction(conn) as tx:
        for row in list_currencies(conn=tx):
            new_rate = int(round(int(row["rate_to_base"]) * money.RATE_SCALE / factor))
            tx.execute(
                "UPDATE currencies SET rate_to_base = ?, is_base = ? WHERE code = ?",
                (new_rate, 1 if row["code"] == code else 0, row["code"]),
            )
        set_value("base_currency", code, conn=tx)
        audit.log("update", "settings", details={"base_currency": code}, conn=tx)

    return True

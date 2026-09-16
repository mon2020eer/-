# -*- coding: utf-8 -*-
"""ترقية مخطط قاعدة البيانات تدريجياً عبر ``PRAGMA user_version``.

لماذا لا نكتفي بـ ``CREATE TABLE IF NOT EXISTS``؟ لأنّها تنشئ الجداول الناقصة
فقط ولا تضيف **عموداً** جديداً إلى جدول قائم عند صدور نسخة أحدث من البرنامج.
لذلك تُسجَّل كل تغيير في القائمة أدناه، ويطبّق التطبيق ما لم يُطبَّق بعد.

قاعدة الإضافة: لا يُعدَّل تعديلٌ قديم أبداً بعد إطلاقه، بل تُضاف خطوة جديدة.
"""


def _columns(conn, table):
    return {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}


def _tables(conn):
    return {row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _add_column(conn, table, column, definition):
    """يضيف عموداً إن لم يكن موجوداً. SQLite لا يعرف ADD COLUMN IF NOT EXISTS."""
    if column not in _columns(conn, table):
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))


def _migration_1(conn):
    """الإصدار الأول: المخطط كاملٌ في schema.sql، فلا شيء إضافي هنا."""
    return None


def _migration_2(conn):
    """الحجز المسبق والاحتساب بالساعة.

    1. يُسقط الفهرس القديم الذي كان يمنع أكثر من عقد مفتوح واحد للسيارة.
       سببه أن المكتب محدود عدد السيارات ويحتاج حجزها لعميل قادم قبل إعادتها.
       بديله مشغّلا منع التداخل في schema.sql، وهما يُنشآن مع كل إقلاع.
    2. يضيف أعمدة الاحتساب بالساعة إلى السيارات والعقود.

    ملاحظة: ``ALTER TABLE ADD COLUMN`` في SQLite لا يقبل قيمة افتراضية غير ثابتة،
    ولذلك تُضاف الأعمدة بقيم ثابتة بسيطة ثم تُملأ للصفوف القائمة.
    """
    conn.execute("DROP INDEX IF EXISTS ux_vehicle_open_contract")

    _add_column(conn, "vehicles", "hourly_rate",
                "INTEGER NOT NULL DEFAULT 0")

    _add_column(conn, "contracts", "start_time", "TEXT NOT NULL DEFAULT '12:00'")
    _add_column(conn, "contracts", "actual_end_time", "TEXT")
    _add_column(conn, "contracts", "hourly_rate_snapshot", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "contracts", "billing_mode", "TEXT NOT NULL DEFAULT 'daily'")
    _add_column(conn, "contracts", "hours_count", "INTEGER NOT NULL DEFAULT 0")

    # العروض تُعاد بناؤها لأن v_contracts_full تختار كل أعمدة العقود
    conn.execute("DROP VIEW IF EXISTS v_contracts_full")


def _migration_3(conn):
    """نموذج المكتب وتنبيهات التأمين والعميل السريع.

    1. **تخفيف قيود العملاء.** ``phone`` و``national_id`` و``license_number``
       كانت ``NOT NULL``، فيستحيل تسجيل زبون واقف أمام الموظّف باسمه وحده.
       وSQLite لا يعرف ``ALTER COLUMN DROP NOT NULL``، فالسبيل الوحيد إعادة بناء
       الجدول: جدول جديد بالتعريف المخفَّف ← نسخ الصفوف ← إسقاط القديم ←
       إعادة التسمية.
    2. أعمدة التأمين والفحص الفنّي في السيارات، وهي مصدر التنبيهات.
    3. أعمدة الكفيل في العقود، تطلبها نماذج المكاتب المطبوعة.
    """
    # --- 0) إسقاط العروض أولاً --------------------------------------------
    # **قبل** أي مساس بجدول العملاء: العروض تشير إليه، وSQLite ترفض إسقاطه أو
    # إعادة تسميته ما دام عرضٌ قائم يذكره («error in view v_contracts_full:
    # no such table: main.customers»). ويعيد ``db.initialize`` بناءها بعد
    # الترقية، وكل عباراتها ``IF NOT EXISTS``.
    conn.execute("DROP VIEW IF EXISTS v_contracts_full")
    conn.execute("DROP VIEW IF EXISTS v_contract_balance")

    # --- 1) إعادة بناء جدول العملاء ---------------------------------------
    # المفاتيح الأجنبية تُعطَّل أثناء إعادة البناء وإلّا اعتبر المحرّك إسقاط
    # الجدول القديم كسراً لمراجع العقود إليه. والمعاملة تضمن ألّا تبقى القاعدة
    # نصف مبنيّة إن انقطع التيار في المنتصف.
    if "customers_v3" not in _tables(conn):
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("""
                CREATE TABLE customers_v3 (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name      TEXT    NOT NULL,
                    phone          TEXT,
                    national_id    TEXT    UNIQUE,
                    license_number TEXT,
                    license_expiry TEXT,
                    nationality    TEXT,
                    address        TEXT,
                    notes          TEXT,
                    is_blacklisted INTEGER NOT NULL DEFAULT 0
                                   CHECK (is_blacklisted IN (0, 1)),
                    created_at     TEXT NOT NULL
                                   DEFAULT (datetime('now', 'localtime')),
                    updated_at     TEXT NOT NULL
                                   DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                INSERT INTO customers_v3 (id, full_name, phone, national_id,
                                          license_number, license_expiry,
                                          nationality, address, notes,
                                          is_blacklisted, created_at, updated_at)
                SELECT id, full_name, phone, national_id, license_number,
                       license_expiry, nationality, address, notes,
                       is_blacklisted, created_at, updated_at
                  FROM customers
            """)
            conn.execute("DROP TABLE customers")
            conn.execute("ALTER TABLE customers_v3 RENAME TO customers")
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    # --- 2) التأمين والفحص الفنّي -----------------------------------------
    _add_column(conn, "vehicles", "insurance_company", "TEXT")
    _add_column(conn, "vehicles", "insurance_policy_no", "TEXT")
    _add_column(conn, "vehicles", "insurance_expiry", "TEXT")
    _add_column(conn, "vehicles", "inspection_expiry", "TEXT")

    # --- 3) الكفيل ---------------------------------------------------------
    _add_column(conn, "contracts", "guarantor_name", "TEXT")
    _add_column(conn, "contracts", "guarantor_nationality", "TEXT")
    _add_column(conn, "contracts", "guarantor_passport", "TEXT")
    _add_column(conn, "contracts", "guarantor_address", "TEXT")



# (رقم الإصدار، الدالة) بترتيب تصاعدي
MIGRATIONS = [
    (1, _migration_1),
    (2, _migration_2),
    (3, _migration_3),
]


def current_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def apply(conn):
    """يطبّق كل الترقيات الأحدث من الإصدار المخزَّن، ويُرجع الإصدار النهائي."""
    version = current_version(conn)

    for target, migrate in MIGRATIONS:
        if target <= version:
            continue
        migrate(conn)
        # PRAGMA لا يقبل المعاملات (parameters)، والقيمة رقم مُولَّد داخلياً
        conn.execute("PRAGMA user_version = %d" % int(target))
        version = target

    return version

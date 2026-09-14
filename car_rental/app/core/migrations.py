# -*- coding: utf-8 -*-
"""ترقية مخطط قاعدة البيانات تدريجياً عبر ``PRAGMA user_version``.

لماذا لا نكتفي بـ ``CREATE TABLE IF NOT EXISTS``؟ لأنّها تنشئ الجداول الناقصة
فقط ولا تضيف **عموداً** جديداً إلى جدول قائم عند صدور نسخة أحدث من البرنامج.
لذلك تُسجَّل كل تغيير في القائمة أدناه، ويطبّق التطبيق ما لم يُطبَّق بعد.

قاعدة الإضافة: لا يُعدَّل تعديلٌ قديم أبداً بعد إطلاقه، بل تُضاف خطوة جديدة.
"""


def _columns(conn, table):
    return {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}


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


# (رقم الإصدار، الدالة) بترتيب تصاعدي
MIGRATIONS = [
    (1, _migration_1),
    (2, _migration_2),
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

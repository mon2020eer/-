# -*- coding: utf-8 -*-
"""ترقية مخطط قاعدة البيانات تدريجياً عبر ``PRAGMA user_version``.

لماذا لا نكتفي بـ ``CREATE TABLE IF NOT EXISTS``؟ لأنّها تنشئ الجداول الناقصة
فقط ولا تضيف **عموداً** جديداً إلى جدول قائم عند صدور نسخة أحدث من البرنامج.
لذلك تُسجَّل كل تغيير في القائمة أدناه، ويطبّق التطبيق ما لم يُطبَّق بعد.

قاعدة الإضافة: لا يُعدَّل تعديلٌ قديم أبداً بعد إطلاقه، بل تُضاف خطوة جديدة.
"""


def _migration_1(conn):
    """الإصدار الأول: المخطط كاملٌ في schema.sql، فلا شيء إضافي هنا."""
    return None


# (رقم الإصدار، الدالة) بترتيب تصاعدي
MIGRATIONS = [
    (1, _migration_1),
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

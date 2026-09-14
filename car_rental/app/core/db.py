# -*- coding: utf-8 -*-
"""طبقة الاتصال بقاعدة بيانات SQLite.

المبادئ المعتمدة:

1. **اتصال واحد لكل خيط** (``threading.local``): كائن اتصال SQLite غير آمن
   للمشاركة بين الخيوط، وخيط النسخ الاحتياطي يعمل بالتوازي مع الواجهة،
   فلكلٍّ اتصاله الخاص.
2. **وضع WAL**: يسمح بقراءة متزامنة أثناء الكتابة، ويقلّل كثيراً من أخطاء
   «قاعدة البيانات مقفلة» عند عمل النسخ الاحتياطي والواجهة معاً.
3. **تفعيل المفاتيح الأجنبية**: SQLite يعطّلها افتراضياً، ولا بدّ من تفعيلها
   في كل اتصال على حدة وإلّا صارت قيود العلاقات مجرّد زينة.
4. **معاملة صريحة** عبر مدير السياق ``transaction()`` مع ``BEGIN IMMEDIATE``،
   فتُحجز الكتابة فوراً وتُتفادى أخطاء التعارض في منتصف العملية.
"""

import contextlib
import pathlib
import sqlite3
import threading

from .. import config

_local = threading.local()
_SCHEMA_FILE = pathlib.Path(__file__).with_name("schema.sql")


def _configure(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def connect(db_path=None):
    """يفتح اتصالاً جديداً مُهيّأً. يُستخدم مباشرةً في الاختبارات والنسخ الاحتياطي."""
    path = pathlib.Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    return _configure(conn)


def get_connection():
    """يُرجع اتصال الخيط الحالي، وينشئه عند أول استدعاء."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def close_connection():
    """يغلق اتصال الخيط الحالي إن وُجد."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


@contextlib.contextmanager
def transaction(conn=None):
    """معاملة ذرّية: إمّا أن تنجح كل العمليات أو لا يُكتب شيء.

    مثال:
        with transaction() as conn:
            conn.execute(...)
            conn.execute(...)
    """
    conn = conn or get_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def query(sql, params=(), conn=None):
    """تنفيذ استعلام قراءة وإرجاع كل الصفوف."""
    conn = conn or get_connection()
    return conn.execute(sql, params).fetchall()


def query_one(sql, params=(), conn=None):
    """تنفيذ استعلام قراءة وإرجاع أول صفّ أو None."""
    conn = conn or get_connection()
    return conn.execute(sql, params).fetchone()


def scalar(sql, params=(), conn=None, default=None):
    """إرجاع القيمة الأولى من الصفّ الأول، أو القيمة الافتراضية."""
    row = query_one(sql, params, conn)
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql, params=(), conn=None):
    """تنفيذ أمر كتابة وإرجاع المؤشّر (فيه lastrowid و rowcount)."""
    conn = conn or get_connection()
    return conn.execute(sql, params)


def initialize(conn=None):
    """ينشئ المخطط إن لم يكن موجوداً، ثم يطبّق الترقيات ويزرع البيانات الأساسية.

    آمن للاستدعاء عند كل إقلاع: كل عبارات المخطط ``IF NOT EXISTS``.
    """
    from . import migrations, seed

    conn = conn or get_connection()
    conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
    migrations.apply(conn)
    seed.ensure_baseline(conn)
    return conn

# -*- coding: utf-8 -*-
"""زرع البيانات الأساسية التي لا يقوم التطبيق بدونها.

يُستدعى عند كل إقلاع وهو **خامل** (idempotent): لا يضيف شيئاً إن كان موجوداً.
"""

from .. import config
from . import security


def ensure_currencies(conn):
    """يزرع العملات الثلاث المدعومة، والعملة الأساس هي الدينار الليبي."""
    defaults = [
        # (الرمز، الاسم، العلامة، سعر الصرف مقابل الأساس ×1,000,000، أهي الأساس؟)
        ("LYD", "دينار ليبي", "د.ل", 1_000_000, 1),
        ("USD", "دولار أمريكي", "$", 5_500_000, 0),
        ("EUR", "يورو", "€", 6_000_000, 0),
    ]
    for code, name_ar, symbol, rate, is_base in defaults:
        conn.execute(
            """INSERT INTO currencies (code, name_ar, symbol, rate_to_base, is_base)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (code) DO NOTHING""",
            (code, name_ar, symbol, rate, is_base),
        )


def ensure_settings(conn):
    """يزرع الإعدادات الافتراضية دون المساس بما عدّله المستخدم."""
    for key, value in config.DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO NOTHING",
            (key, value),
        )


def ensure_admin(conn):
    """ينشئ حساب المدير الأول إن لم يوجد أي مستخدم.

    كلمة المرور الافتراضية مؤقّتة، والحقل ``must_change_password`` يُجبر
    المستخدم على تغييرها فور أول دخول.
    """
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count:
        return False

    conn.execute(
        """INSERT INTO users (username, full_name, password_hash, role,
                              must_change_password)
           VALUES (?, ?, ?, 'admin', 1)""",
        (
            config.DEFAULT_ADMIN_USERNAME,
            "مدير المنظومة",
            security.hash_password(config.DEFAULT_ADMIN_PASSWORD),
        ),
    )
    return True


def ensure_baseline(conn):
    """يشغّل كل عمليات الزرع داخل معاملة واحدة."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_currencies(conn)
        ensure_settings(conn)
        created_admin = ensure_admin(conn)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return created_admin

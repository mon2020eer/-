# -*- coding: utf-8 -*-
"""مستودع المستخدمين: المصادقة وإدارة الحسابات."""

import datetime

from .. import config
from ..core import audit, db, features, security, session


class AuthError(Exception):
    """خطأ مصادقة برسالة عربية جاهزة للعرض."""


def get(user_id, conn=None):
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)


def get_by_username(username, conn=None):
    return db.query_one(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,), conn=conn
    )


def list_all(include_inactive=True, conn=None):
    sql = "SELECT * FROM users"
    if not include_inactive:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY role, full_name"
    return db.query(sql, conn=conn)


def count_active_admins(conn=None):
    return db.scalar(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1",
        conn=conn,
        default=0,
    )


def _is_locked(row):
    """هل الحساب مقفل مؤقّتاً بسبب محاولات دخول فاشلة متتابعة؟"""
    locked_until = row["locked_until"]
    if not locked_until:
        return False
    try:
        until = datetime.datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return until > datetime.datetime.now()


def authenticate(username, password, conn=None):
    """يتحقّق من بيانات الدخول ويُرجع ``CurrentUser`` عند النجاح.

    يرفع ``AuthError`` برسالة عربية عند الفشل. الرسالة موحّدة عمداً عند خطأ
    الاسم أو كلمة المرور، فلا تكشف أيّ أسماء المستخدمين موجود فعلاً.
    """
    row = get_by_username((username or "").strip(), conn=conn)

    if row is None:
        audit.log("login_failed", "user", details={"username": username}, conn=conn)
        raise AuthError("اسم المستخدم أو كلمة المرور غير صحيحة.")

    if not row["is_active"]:
        raise AuthError("هذا الحساب معطَّل. راجع مدير المنظومة.")

    if _is_locked(row):
        raise AuthError(
            "الحساب مقفل مؤقّتاً بسبب محاولات دخول فاشلة. أعد المحاولة بعد %d دقيقة."
            % config.LOCK_MINUTES
        )

    if not security.verify_password(password, row["password_hash"]):
        _register_failure(row, conn=conn)
        raise AuthError("اسم المستخدم أو كلمة المرور غير صحيحة.")

    # نجاح: تصفير العدّاد وتحديث آخر دخول
    db.execute(
        """UPDATE users
              SET failed_attempts = 0, locked_until = NULL,
                  last_login_at = datetime('now', 'localtime')
            WHERE id = ?""",
        (row["id"],),
        conn=conn,
    )

    # تجديد البصمة تلقائياً إن كانت مولَّدة بعدد دورات أقلّ من الحالي
    if security.needs_rehash(row["password_hash"]):
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (security.hash_password(password), row["id"]),
            conn=conn,
        )

    user = session.CurrentUser.from_row(row)
    session.login(user)
    audit.log("login", "user", row["id"], conn=conn, user=user)
    return user


def _register_failure(row, conn=None):
    attempts = int(row["failed_attempts"] or 0) + 1
    locked_until = None

    if attempts >= config.MAX_FAILED_ATTEMPTS:
        until = datetime.datetime.now() + datetime.timedelta(minutes=config.LOCK_MINUTES)
        locked_until = until.strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
        (attempts, locked_until, row["id"]),
        conn=conn,
    )
    audit.log("login_failed", "user", row["id"], {"attempts": attempts}, conn=conn)


def must_change_password(user_id, conn=None):
    row = get(user_id, conn=conn)
    return bool(row and row["must_change_password"])


@session.requires_role("admin")
@features.requires_feature("multi_user")
def create(username, full_name, password, role, phone=None, conn=None):
    """ينشئ مستخدماً جديداً — للمدير فقط."""
    username = (username or "").strip()
    if not username:
        raise ValueError("اسم المستخدم مطلوب.")
    if role not in ("admin", "staff"):
        raise ValueError("الصلاحية غير معروفة.")
    if get_by_username(username, conn=conn):
        raise ValueError("اسم المستخدم مستخدَم بالفعل.")

    problems = security.check_password_policy(password, config.MIN_PASSWORD_LENGTH)
    if problems:
        raise ValueError(" ".join(problems))

    with db.transaction(conn) as tx:
        cursor = tx.execute(
            """INSERT INTO users (username, full_name, password_hash, role, phone)
               VALUES (?, ?, ?, ?, ?)""",
            (username, full_name.strip(), security.hash_password(password), role, phone),
        )
        user_id = cursor.lastrowid
        audit.log("create", "user", user_id, {"username": username, "role": role}, conn=tx)

    return user_id


@session.requires_role("admin")
def update(user_id, full_name=None, role=None, phone=None, is_active=None, conn=None):
    """يعدّل بيانات مستخدم — للمدير فقط."""
    # إدارة المستخدمين (الصلاحية والتفعيل) ميزةُ النسخة المتقدّمة. أمّا تصحيح
    # اسم الحساب أو هاتفه فيبقى متاحاً لصاحب الحساب الواحد في الأساسية.
    if role is not None or is_active is not None:
        features.require("multi_user")

    fields, params = [], []
    for column, value in (
        ("full_name", full_name),
        ("role", role),
        ("phone", phone),
        ("is_active", is_active),
    ):
        if value is not None:
            fields.append("%s = ?" % column)
            params.append(value)

    if not fields:
        return False

    params.append(user_id)
    # القراءة والفحص والتعديل تحت قفل الكتابة نفسه: لو قُرئ العدد قبل ``BEGIN``
    # لرأى مديران متزامنان مديرَين فعّالين ثم عطّل كلٌّ منهما الآخر، فبقيت
    # المنظومة بلا مدير — وهي حالة لا تُصلَح من داخل التطبيق.
    with db.transaction(conn) as tx:
        row = get(user_id, conn=tx)
        if row is None:
            raise ValueError("المستخدم غير موجود.")

        # حماية جوهرية: لا يجوز أن تفقد المنظومة آخر مدير فعّال
        losing_admin = (
            (role is not None and role != "admin" and row["role"] == "admin")
            or (is_active == 0 and row["role"] == "admin")
        )
        if losing_admin and count_active_admins(conn=tx) <= 1:
            raise ValueError("لا يمكن تعطيل آخر حساب مدير في المنظومة.")

        tx.execute("UPDATE users SET %s WHERE id = ?" % ", ".join(fields), params)
        audit.log("update", "user", user_id, {"fields": fields}, conn=tx)
    return True


def change_password(user_id, new_password, require_policy=True, conn=None):
    """يغيّر كلمة مرور مستخدم ويلغي إلزام التغيير."""
    if require_policy:
        problems = security.check_password_policy(new_password, config.MIN_PASSWORD_LENGTH)
        if problems:
            raise ValueError(" ".join(problems))

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE users
                  SET password_hash = ?, must_change_password = 0,
                      failed_attempts = 0, locked_until = NULL
                WHERE id = ?""",
            (security.hash_password(new_password), user_id),
        )
        audit.log("password_change", "user", user_id, conn=tx)
    return True


@session.requires_role("admin")
def reset_password(user_id, new_password, conn=None):
    """يعيد المدير ضبط كلمة مرور مستخدم، مع إلزامه بتغييرها عند أول دخول."""
    problems = security.check_password_policy(new_password, config.MIN_PASSWORD_LENGTH)
    if problems:
        raise ValueError(" ".join(problems))

    with db.transaction(conn) as tx:
        tx.execute(
            """UPDATE users
                  SET password_hash = ?, must_change_password = 1,
                      failed_attempts = 0, locked_until = NULL
                WHERE id = ?""",
            (security.hash_password(new_password), user_id),
        )
        audit.log("password_change", "user", user_id, {"by_admin": True}, conn=tx)
    return True

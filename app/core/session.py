# -*- coding: utf-8 -*-
"""جلسة المستخدم الحالي والتحقّق من الصلاحيات.

الصلاحيات تُفرض في **طبقة الخدمة** لا في الواجهة فقط. إخفاء زرّ في الواجهة
إجراء تجميلي؛ أمّا المُزخرف ``requires_role`` فيمنع تنفيذ العملية أصلاً مهما
كان مصدر الاستدعاء.
"""

import functools
import threading

_state = threading.local()


class PermissionDenied(Exception):
    """تُرفع عند محاولة تنفيذ عملية خارج صلاحية المستخدم الحالي."""


class CurrentUser(object):
    """صورة مبسّطة عن المستخدم الجالس أمام الشاشة."""

    __slots__ = ("id", "username", "full_name", "role")

    def __init__(self, user_id, username, full_name, role):
        self.id = user_id
        self.username = username
        self.full_name = full_name
        self.role = role

    @property
    def is_admin(self):
        return self.role == "admin"

    @classmethod
    def from_row(cls, row):
        return cls(row["id"], row["username"], row["full_name"], row["role"])


def login(user):
    """يثبّت المستخدم الحالي بعد نجاح المصادقة."""
    _state.user = user
    return user


def logout():
    _state.user = None


def current_user():
    return getattr(_state, "user", None)


def current_user_id():
    user = current_user()
    return user.id if user else None


def has_role(*roles):
    user = current_user()
    return bool(user) and user.role in roles


def require_login():
    user = current_user()
    if user is None:
        raise PermissionDenied("يجب تسجيل الدخول أولاً.")
    return user


def requires_role(*roles):
    """مُزخرف يمنع تنفيذ الدالة إن لم يكن دور المستخدم ضمن الأدوار المسموحة.

    مثال:
        @requires_role("admin")
        def delete_vehicle(vehicle_id): ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = require_login()
            if user.role not in roles:
                raise PermissionDenied(
                    "هذه العملية متاحة لصلاحية «%s» فقط."
                    % "، ".join({"admin": "مدير", "staff": "موظّف"}.get(r, r) for r in roles)
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator

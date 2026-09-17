# -*- coding: utf-8 -*-
"""سجلّ التدقيق: تسجيل العمليات الحسّاسة مع صاحبها ووقتها.

يُكتب اسم المستخدم نصّاً إلى جانب معرّفه، فيبقى السجل مفهوماً حتى بعد تعطيل
الحساب أو تغيير اسمه.
"""

import json

from . import db, session

# تسميات عربية تُستخدم في شاشة سجلّ التدقيق
ACTION_LABELS = {
    "login": "تسجيل دخول",
    "login_failed": "محاولة دخول فاشلة",
    "logout": "تسجيل خروج",
    "create": "إضافة",
    "update": "تعديل",
    "delete": "حذف",
    "close": "إغلاق",
    "cancel": "إلغاء",
    "payment": "تسجيل دفعة",
    "backup": "نسخ احتياطي",
    "restore": "استعادة نسخة",
    "password_change": "تغيير كلمة المرور",
    "export": "تصدير بيانات",
}

ENTITY_LABELS = {
    "user": "مستخدم",
    "customer": "عميل",
    "vehicle": "سيارة",
    "contract": "عقد",
    "payment": "دفعة",
    "maintenance": "صيانة",
    "violation": "مخالفة",
    "backup": "نسخة احتياطية",
    "settings": "إعدادات",
}


def log(action, entity, entity_id=None, details=None, conn=None, user=None):
    """يكتب سطراً في سجلّ التدقيق.

    لا يُرفع أي استثناء إلى المستدعي: فشل الكتابة في السجل يجب ألّا يُفشل
    العملية الأصلية (تسجيل عقد مثلاً).
    """
    user = user or session.current_user()
    payload = json.dumps(details, ensure_ascii=False) if details else None

    try:
        db.execute(
            """INSERT INTO audit_log (user_id, username, action, entity, entity_id, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user.id if user else None,
                user.username if user else None,
                action,
                entity,
                entity_id,
                payload,
            ),
            conn=conn,
        )
    except Exception:  # pragma: no cover - السجل مساعد لا حرج
        pass


def recent(limit=200, conn=None):
    """آخر العمليات المسجَّلة، الأحدث أولاً."""
    return db.query(
        """SELECT * FROM audit_log ORDER BY id DESC LIMIT ?""",
        (int(limit),),
        conn=conn,
    )

# -*- coding: utf-8 -*-
"""تعمية كلمات المرور والتحقّق منها.

الخوارزمية: **PBKDF2-HMAC-SHA256** من المكتبة القياسية ``hashlib``.

لماذا لا bcrypt؟ لأنّها تبعية ثنائية (binary) تسبّب مشاكل متكرّرة عند حزم
التطبيق بـ PyInstaller على ويندوز، بينما PBKDF2 مدمجة في بايثون نفسها ومعتمدة
من NIST. عدد الدورات مرتفع عمداً ليجعل تخمين كلمة المرور مكلفاً.

صيغة التخزين — سلسلة نصية واحدة مكتفية بذاتها، تحمل معها معاملاتها:

    pbkdf2_sha256$<عدد الدورات>$<الملح base64>$<البصمة base64>

وفائدتها أن رفع عدد الدورات مستقبلاً لا يُبطل كلمات المرور القديمة، لأن كل
بصمة تحمل عدد دوراتها هي.
"""

import base64
import hashlib
import hmac
import os
import re

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 480_000
SALT_BYTES = 16
HASH_BYTES = 32


def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


def _unb64(text):
    return base64.b64decode(text.encode("ascii"))


def _derive(password, salt, iterations):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=HASH_BYTES
    )


def hash_password(password, iterations=ITERATIONS):
    """يُنتج بصمة كلمة مرور جديدة بملح عشوائي خاص بها."""
    if not isinstance(password, str) or not password:
        raise ValueError("كلمة المرور مطلوبة")

    salt = os.urandom(SALT_BYTES)
    digest = _derive(password, salt, iterations)
    return "%s$%d$%s$%s" % (ALGORITHM, iterations, _b64(salt), _b64(digest))


def verify_password(password, stored):
    """يتحقّق من كلمة المرور مقابل البصمة المخزَّنة.

    تُستخدم ``hmac.compare_digest`` لا ``==`` لتفادي هجمات توقيت المقارنة.
    """
    if not password or not stored:
        return False

    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        expected = _unb64(digest_b64)
        actual = _derive(password, _unb64(salt_b64), int(iterations))
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(expected, actual)


def needs_rehash(stored, iterations=ITERATIONS):
    """هل البصمة مولَّدة بعدد دورات أقلّ من الحالي فتستحق التجديد؟"""
    try:
        algorithm, stored_iterations, _, _ = stored.split("$")
    except (ValueError, AttributeError):
        return True
    return algorithm != ALGORITHM or int(stored_iterations) < iterations


def check_password_policy(password, min_length=8):
    """يفحص قوّة كلمة المرور ويُرجع قائمة رسائل عربية بالمخالفات.

    قائمة فارغة تعني أن كلمة المرور مقبولة.
    """
    problems = []

    if not password or len(password) < min_length:
        problems.append("يجب ألّا تقلّ كلمة المرور عن %d محارف." % min_length)
    if password and not re.search(r"[A-Za-z؀-ۿ]", password):
        problems.append("يجب أن تحتوي كلمة المرور على حرف واحد على الأقل.")
    if password and not re.search(r"\d", password):
        problems.append("يجب أن تحتوي كلمة المرور على رقم واحد على الأقل.")
    if password and password.lower() in ("password", "12345678", "admin123"):
        problems.append("كلمة المرور شائعة جداً ويسهل تخمينها.")

    return problems

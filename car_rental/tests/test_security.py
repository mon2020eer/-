# -*- coding: utf-8 -*-
"""اختبارات تعمية كلمات المرور والمصادقة وقفل الحساب."""

import pytest

from app import config
from app.core import security, session


# --- التعمية ---------------------------------------------------------------
def test_hash_is_verifiable():
    stored = security.hash_password("Passw0rd!", iterations=1000)
    assert security.verify_password("Passw0rd!", stored)


def test_wrong_password_is_rejected():
    stored = security.hash_password("Passw0rd!", iterations=1000)
    assert not security.verify_password("passw0rd!", stored)


def test_salt_differs_per_hash():
    """بصمتان لكلمة المرور نفسها يجب أن تختلفا بفضل الملح العشوائي."""
    first = security.hash_password("SamePass1", iterations=1000)
    second = security.hash_password("SamePass1", iterations=1000)
    assert first != second
    assert security.verify_password("SamePass1", first)
    assert security.verify_password("SamePass1", second)


def test_corrupt_hash_does_not_crash():
    assert not security.verify_password("anything", "ليست-بصمة-صالحة")
    assert not security.verify_password("anything", "")
    assert not security.verify_password("", None)


def test_needs_rehash_for_lower_iterations():
    stored = security.hash_password("SamePass1", iterations=1000)
    assert security.needs_rehash(stored, iterations=480000)
    assert not security.needs_rehash(stored, iterations=1000)


def test_password_policy():
    assert security.check_password_policy("قصيرة1")          # أقصر من الحد
    assert security.check_password_policy("12345678")         # بلا حروف
    assert security.check_password_policy("abcdefgh")         # بلا أرقام
    assert not security.check_password_policy("Sayara2026")   # مقبولة


# --- المصادقة --------------------------------------------------------------
def test_default_admin_can_login(conn):
    from app.repositories import users_repo

    user = users_repo.authenticate(
        config.DEFAULT_ADMIN_USERNAME, config.DEFAULT_ADMIN_PASSWORD, conn=conn
    )
    assert user.is_admin
    assert session.current_user().id == user.id


def test_default_admin_must_change_password(conn, admin):
    from app.repositories import users_repo

    assert users_repo.must_change_password(admin.id, conn=conn)
    users_repo.change_password(admin.id, "Sayara2026", conn=conn)
    assert not users_repo.must_change_password(admin.id, conn=conn)


def test_bad_password_raises_auth_error(conn):
    from app.repositories import users_repo

    with pytest.raises(users_repo.AuthError):
        users_repo.authenticate("admin", "خطأ-تماماً", conn=conn)


def test_account_locks_after_repeated_failures(conn):
    from app.repositories import users_repo

    for _ in range(config.MAX_FAILED_ATTEMPTS):
        with pytest.raises(users_repo.AuthError):
            users_repo.authenticate("admin", "خطأ", conn=conn)

    # حتى كلمة المرور الصحيحة تُرفض أثناء القفل
    with pytest.raises(users_repo.AuthError) as error:
        users_repo.authenticate("admin", config.DEFAULT_ADMIN_PASSWORD, conn=conn)
    assert "مقفل" in str(error.value)


# --- الصلاحيات -------------------------------------------------------------
def test_staff_cannot_create_users(conn, admin):
    from app.repositories import users_repo

    users_repo.create("kamal", "كمال الموظّف", "Sayara2026", "staff", conn=conn)
    staff = users_repo.authenticate("kamal", "Sayara2026", conn=conn)
    assert staff.role == "staff"

    with pytest.raises(session.PermissionDenied):
        users_repo.create("other", "آخر", "Sayara2026", "staff", conn=conn)


def test_cannot_disable_last_admin(conn, admin):
    from app.repositories import users_repo

    with pytest.raises(ValueError) as error:
        users_repo.update(admin.id, is_active=0, conn=conn)
    assert "آخر حساب مدير" in str(error.value)


def test_logged_out_user_cannot_act(conn, admin):
    from app.repositories import customers_repo

    session.logout()
    with pytest.raises(session.PermissionDenied):
        customers_repo.create({"full_name": "س", "phone": "1", "national_id": "1",
                               "license_number": "1"}, conn=conn)


def test_last_admin_check_runs_inside_the_write_transaction(conn, admin, monkeypatch):
    """عدّ المديرين الفعّالين يجري تحت قفل الكتابة لا قبله.

    لو جرى قبله لرأى مديران متزامنان مديرَين فعّالين، ثم عطّل كلٌّ منهما
    الآخر — فتصبح المنظومة بلا مدير، وهي حالة لا تُصلَح من داخل التطبيق.
    """
    from app.repositories import users_repo

    users_repo.create("thani", "المدير الثاني", "Sayara2026", "admin", conn=conn)

    seen = {}
    original = users_repo.count_active_admins

    def spy(conn=None):
        seen["locked"] = bool(conn is not None and conn.in_transaction)
        return original(conn=conn)

    monkeypatch.setattr(users_repo, "count_active_admins", spy)
    users_repo.update(admin.id, is_active=0, conn=conn)

    assert seen.get("locked") is True

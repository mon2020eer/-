# -*- coding: utf-8 -*-
"""تهيئة مشتركة للاختبارات.

كل اختبار يعمل على **قاعدة بيانات مؤقّتة معزولة** عبر توجيه متغيّر البيئة
``CAR_RENTAL_HOME`` إلى مجلد مؤقّت قبل استيراد أي وحدة من التطبيق، فلا
تُلمس بيانات التشغيل الحقيقية إطلاقاً.
"""

import os
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture()
def app_home(tmp_path, monkeypatch):
    """يوجّه مجلد بيانات التطبيق إلى مجلد مؤقّت ويعيد تهيئة المسارات."""
    monkeypatch.setenv("CAR_RENTAL_HOME", str(tmp_path))

    from app import config
    from app.core import db

    db.close_connection()
    config.reload_paths()
    config.ensure_directories()
    yield tmp_path
    db.close_connection()


@pytest.fixture()
def conn(app_home):
    """قاعدة بيانات مهيّأة بالمخطط الكامل والبيانات الأساسية."""
    from app.core import db

    connection = db.initialize()
    yield connection
    db.close_connection()


@pytest.fixture()
def admin(conn):
    """يسجّل دخول حساب المدير الافتراضي ويُرجعه."""
    from app import config
    from app.repositories import users_repo

    return users_repo.authenticate(
        config.DEFAULT_ADMIN_USERNAME, config.DEFAULT_ADMIN_PASSWORD, conn=conn
    )


@pytest.fixture()
def sample_customer(admin, conn):
    from app.repositories import customers_repo

    return customers_repo.create(
        {
            "full_name": "محمد علي الشريف",
            "phone": "0912345678",
            "national_id": "119876543210",
            "license_number": "LC-4455",
            "license_expiry": "2030-01-01",
        },
        conn=conn,
    )


@pytest.fixture()
def sample_vehicle(admin, conn):
    from app.repositories import vehicles_repo

    return vehicles_repo.create(
        {
            "brand": "تويوتا",
            "model": "كورولا",
            "year": 2022,
            "plate_number": "5-12345",
            "color": "أبيض",
            "daily_rate": 15000,     # 150.00
            "weekly_rate": 90000,    # 900.00
            "currency_code": "LYD",
            "odometer": 42000,
        },
        conn=conn,
    )


@pytest.fixture(scope="session", autouse=True)
def _offscreen_qt():
    """يمنع Qt من محاولة فتح نافذة حقيقية في بيئة الاختبار."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tempfile.gettempdir()

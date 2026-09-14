# -*- coding: utf-8 -*-
"""اختبار ترقية قاعدة بيانات قائمة من الإصدار الأول إلى الثاني.

هذا الاختبار يحاكي ما يحدث للمكتب الذي يعمل بالنسخة الأولى فعلاً: قاعدة بياناته
مليئة بعقود حقيقية، ثم يُحدِّث البرنامج. يجب أن:
    • تُضاف أعمدة الاحتساب بالساعة،
    • يُسقَط الفهرس القديم الذي كان يمنع أكثر من عقد مفتوح واحد،
    • ويصير الحجز المسبق ممكناً، مع بقاء منع التداخل،
    • **ولا تضيع سطر واحد من بياناته**.
"""

import datetime
import sqlite3

import pytest

from app.core import db, migrations


def _build_v1_database(path):
    """ينشئ قاعدة بيانات بمخطط الإصدار الأول كما كان مطلوقاً."""
    conn = db.connect(path)
    conn.executescript(
        """
        CREATE TABLE currencies (
            code TEXT PRIMARY KEY, name_ar TEXT NOT NULL, symbol TEXT NOT NULL,
            decimals INTEGER NOT NULL DEFAULT 2,
            rate_to_base INTEGER NOT NULL DEFAULT 1000000,
            is_base INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin','staff')), phone TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT,
            last_login_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
            phone TEXT NOT NULL, national_id TEXT NOT NULL UNIQUE,
            license_number TEXT NOT NULL, license_expiry TEXT, nationality TEXT,
            address TEXT, notes TEXT, is_blacklisted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

        CREATE TABLE vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, brand TEXT NOT NULL,
            model TEXT NOT NULL, year INTEGER NOT NULL, plate_number TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL, daily_rate INTEGER NOT NULL,
            weekly_rate INTEGER NOT NULL DEFAULT 0,
            currency_code TEXT NOT NULL REFERENCES currencies (code),
            status TEXT NOT NULL DEFAULT 'available',
            odometer INTEGER NOT NULL DEFAULT 0, chassis_number TEXT, notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

        CREATE TABLE contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, contract_number TEXT NOT NULL UNIQUE,
            customer_id INTEGER NOT NULL REFERENCES customers (id),
            vehicle_id INTEGER NOT NULL REFERENCES vehicles (id),
            start_date TEXT NOT NULL, expected_end_date TEXT NOT NULL,
            actual_end_date TEXT,
            daily_rate_snapshot INTEGER NOT NULL,
            weekly_rate_snapshot INTEGER NOT NULL DEFAULT 0,
            currency_code TEXT NOT NULL REFERENCES currencies (code),
            rate_to_base INTEGER NOT NULL, days_count INTEGER NOT NULL,
            subtotal INTEGER NOT NULL, discount INTEGER NOT NULL DEFAULT 0,
            extra_charges INTEGER NOT NULL DEFAULT 0, total_amount INTEGER NOT NULL,
            start_odometer INTEGER, end_odometer INTEGER, pickup_location TEXT,
            return_location TEXT, status TEXT NOT NULL DEFAULT 'open',
            notes TEXT, created_by INTEGER NOT NULL REFERENCES users (id),
            closed_by INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            closed_at TEXT);

        CREATE TABLE payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER NOT NULL REFERENCES contracts (id) ON DELETE CASCADE,
            amount INTEGER NOT NULL, method TEXT NOT NULL DEFAULT 'cash',
            kind TEXT NOT NULL DEFAULT 'payment',
            paid_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            reference TEXT, note TEXT,
            recorded_by INTEGER NOT NULL REFERENCES users (id));

        -- القيد القديم الذي صار يعطّل المكتب
        CREATE UNIQUE INDEX ux_vehicle_open_contract
            ON contracts (vehicle_id) WHERE status = 'open';

        PRAGMA user_version = 1;
        """
    )

    today = datetime.date.today()
    conn.execute(
        "INSERT INTO currencies (code, name_ar, symbol, is_base) VALUES ('LYD','دينار','د.ل',1)"
    )
    conn.execute(
        "INSERT INTO users (username, full_name, password_hash, role) "
        "VALUES ('admin','مدير','x','admin')"
    )
    conn.execute(
        "INSERT INTO customers (full_name, phone, national_id, license_number) "
        "VALUES ('عميل قديم','0910000000','OLD-1','LC-1')"
    )
    conn.execute(
        "INSERT INTO vehicles (brand, model, year, plate_number, color, daily_rate, "
        "currency_code, status) VALUES ('تويوتا','كورولا',2020,'9-00001','أبيض',15000,'LYD','rented')"
    )
    conn.execute(
        """INSERT INTO contracts (contract_number, customer_id, vehicle_id, start_date,
                                  expected_end_date, daily_rate_snapshot, currency_code,
                                  rate_to_base, days_count, subtotal, total_amount, created_by)
           VALUES ('CR-2025-0001', 1, 1, ?, ?, 15000, 'LYD', 1000000, 3, 45000, 45000, 1)""",
        (today.isoformat(), (today + datetime.timedelta(days=3)).isoformat()),
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def upgraded(app_home):
    """قاعدة بيانات من الإصدار الأول بعد تشغيل الترقية عليها."""
    from app import config

    _build_v1_database(config.DB_PATH)
    conn = db.initialize()
    yield conn
    db.close_connection()


def test_version_is_upgraded(upgraded):
    assert migrations.current_version(upgraded) == 2


def test_existing_data_survives_the_upgrade(upgraded):
    """الترقية لا تفقد صفّاً واحداً من بيانات المكتب."""
    assert upgraded.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1
    assert upgraded.execute(
        "SELECT contract_number FROM contracts"
    ).fetchone()[0] == "CR-2025-0001"
    assert upgraded.execute(
        "SELECT full_name FROM customers"
    ).fetchone()[0] == "عميل قديم"


def test_new_columns_exist_with_sane_defaults(upgraded):
    contract = upgraded.execute("SELECT * FROM contracts").fetchone()
    assert contract["start_time"] == "12:00"
    assert contract["billing_mode"] == "daily"
    assert contract["hours_count"] == 0
    assert contract["hourly_rate_snapshot"] == 0
    assert upgraded.execute("SELECT hourly_rate FROM vehicles").fetchone()[0] == 0


def test_old_single_open_contract_index_is_gone(upgraded):
    names = {row[0] for row in upgraded.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    )}
    assert "ux_vehicle_open_contract" not in names


def test_advance_booking_works_after_upgrade(upgraded):
    """ثمرة الترقية: السيارة المؤجَّرة تُحجَز لفترة لاحقة."""
    today = datetime.date.today()
    upgraded.execute(
        """INSERT INTO contracts (contract_number, customer_id, vehicle_id, start_date,
                                  expected_end_date, daily_rate_snapshot, currency_code,
                                  rate_to_base, days_count, subtotal, total_amount, created_by)
           VALUES ('CR-2025-0002', 1, 1, ?, ?, 15000, 'LYD', 1000000, 2, 30000, 30000, 1)""",
        ((today + datetime.timedelta(days=5)).isoformat(),
         (today + datetime.timedelta(days=7)).isoformat()),
    )
    assert upgraded.execute(
        "SELECT COUNT(*) FROM contracts WHERE status = 'open'"
    ).fetchone()[0] == 2


def test_overlap_protection_is_active_after_upgrade(upgraded):
    """ولا تضيع الحماية: التداخل في الأيام نفسها ما زال مرفوضاً."""
    today = datetime.date.today()
    with pytest.raises(sqlite3.IntegrityError) as error:
        upgraded.execute(
            """INSERT INTO contracts (contract_number, customer_id, vehicle_id, start_date,
                                      expected_end_date, daily_rate_snapshot, currency_code,
                                      rate_to_base, days_count, subtotal, total_amount,
                                      created_by)
               VALUES ('CR-2025-0003', 1, 1, ?, ?, 15000, 'LYD', 1000000, 1, 15000, 15000, 1)""",
            ((today + datetime.timedelta(days=1)).isoformat(),
             (today + datetime.timedelta(days=2)).isoformat()),
        )
    assert "contract_period_overlap" in str(error.value)


def test_views_are_rebuilt_after_upgrade(upgraded):
    """العرض المُسقَط أثناء الترقية يُعاد بناؤه، ويحمل الأعمدة الجديدة."""
    row = upgraded.execute("SELECT * FROM v_contracts_full").fetchone()
    assert row["contract_number"] == "CR-2025-0001"
    assert "billing_mode" in row.keys()


def test_migration_is_idempotent(upgraded):
    """إعادة التهيئة مرّة أخرى لا تُفسد شيئاً ولا تُكرّر عملاً."""
    db.initialize(upgraded)
    assert migrations.current_version(upgraded) == 2
    assert upgraded.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1

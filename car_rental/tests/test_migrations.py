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


def _latest_version():
    """آخر إصدار في قائمة الترقيات — فلا يحتاج الاختبار تعديلاً مع كل ترقية."""
    return max(number for number, _ in migrations.MIGRATIONS)


def test_version_is_upgraded(upgraded):
    assert migrations.current_version(upgraded) == _latest_version()


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
    assert migrations.current_version(upgraded) == _latest_version()
    assert upgraded.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# الترقية ٣: العميل الناقص والتأمين والكفيل
# ---------------------------------------------------------------------------
def test_customer_columns_become_optional(upgraded):
    """إعادة بناء جدول العملاء تُسقط NOT NULL عن الهاتف والرقم والرخصة."""
    columns = {row[1]: row for row in upgraded.execute("PRAGMA table_info(customers)")}

    for name in ("phone", "national_id", "license_number"):
        assert columns[name][3] == 0, "%s ما زال NOT NULL" % name
    # والاسم يبقى إلزامياً: عميل بلا اسم لا معنى له
    assert columns["full_name"][3] == 1


def test_customer_can_be_created_with_a_name_only(upgraded):
    upgraded.execute("INSERT INTO customers (full_name) VALUES (?)", ("زبون عابر",))
    upgraded.commit()

    row = upgraded.execute(
        "SELECT phone, national_id, license_number FROM customers"
        " WHERE full_name = ?", ("زبون عابر",)
    ).fetchone()
    assert tuple(row) == (None, None, None)


def test_national_id_stays_unique_but_allows_many_empties(upgraded):
    """التفرّد يبقى حارساً، وSQLite تسمح بتكرار NULL فيه — وهو ما نريده."""
    import sqlite3

    upgraded.execute("INSERT INTO customers (full_name) VALUES ('أول')")
    upgraded.execute("INSERT INTO customers (full_name) VALUES ('ثانٍ')")
    upgraded.commit()          # ناقصان معاً ولا تعارض

    upgraded.execute(
        "INSERT INTO customers (full_name, national_id) VALUES ('ثالث', 'ID-9')"
    )
    upgraded.commit()

    with pytest.raises(sqlite3.IntegrityError):
        upgraded.execute(
            "INSERT INTO customers (full_name, national_id) VALUES ('رابع', 'ID-9')"
        )


def test_existing_customers_survive_the_rebuild(upgraded):
    """إعادة بناء الجدول لا تفقد صفّاً ولا تغيّر معرّفاً ترتبط به العقود."""
    rows = upgraded.execute(
        "SELECT id, full_name, national_id FROM customers ORDER BY id"
    ).fetchall()
    assert rows, "لم يبقَ عميل بعد الترقية"

    orphans = upgraded.execute(
        "SELECT COUNT(*) FROM contracts c"
        " LEFT JOIN customers cu ON cu.id = c.customer_id"
        " WHERE cu.id IS NULL"
    ).fetchone()[0]
    assert orphans == 0, "عقود فقدت عملاءها بعد إعادة البناء"


def test_insurance_and_guarantor_columns_exist(upgraded):
    vehicle_columns = {row[1] for row in upgraded.execute("PRAGMA table_info(vehicles)")}
    for name in ("insurance_company", "insurance_policy_no",
                 "insurance_expiry", "inspection_expiry"):
        assert name in vehicle_columns, name

    contract_columns = {row[1] for row in
                        upgraded.execute("PRAGMA table_info(contracts)")}
    for name in ("guarantor_name", "guarantor_nationality",
                 "guarantor_passport", "guarantor_address"):
        assert name in contract_columns, name


def test_upgrade_works_when_views_already_exist(app_home):
    """الترقية على قاعدة **مستعمَلة** لا على واحدة نظيفة.

    الحالة الواقعية: قاعدة وصلت الإصدار ٢ وأُعيد بناء عروضها، ثم صدر تحديث.
    وSQLite ترفض إسقاط جدول العملاء أو إعادة تسميته ما دام عرضٌ قائم يذكره،
    فتنهار الترقية برسالة مُضلّلة «no such table: main.customers».
    وهذا ما وقع فعلاً عند أول تشغيل بعد التحديث.
    """
    from app.core import db, migrations

    connection = db.initialize()
    assert migrations.current_version(connection) == _latest_version()

    views = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        )
    }
    assert {"v_contracts_full", "v_contract_balance"} <= views

    # نُرجع رقم الإصدار وحده: الجداول والعروض تبقى كما هي، فتُعاد الترقية ٣
    # على قاعدة عروضها قائمة — وهي الحالة التي كانت تنهار.
    connection.execute("PRAGMA user_version = 2")
    connection.commit()

    db.initialize(connection)          # يجب ألّا يرفع استثناءً
    assert migrations.current_version(connection) == _latest_version()

    connection.execute("INSERT INTO customers (full_name) VALUES ('بعد الترقية')")
    connection.commit()
    assert connection.execute(
        "SELECT COUNT(*) FROM v_contracts_full"
    ).fetchone()[0] is not None


# ---------------------------------------------------------------------------
# ذرّية الترقية: إمّا تمّت أو لم يقع منها شيء
# ---------------------------------------------------------------------------
def test_a_failed_migration_does_not_advance_the_version(app_home, monkeypatch):
    """ترقية تعثّرت في منتصفها لا تُسجَّل ناجحة ولا تترك أثراً نصفياً.

    كانت إعادة بناء جدول العملاء تجري بلا معاملة، فإن فشلت عبارة بعد إنشاء
    `customers_v3` بقي الجدول المؤقّت؛ ويعدّه التشغيل التالي دليلَ اكتمال
    فيتخطّى البناء ثم يرفع رقم الإصدار إلى ٣ — وجدول العملاء ما يزال بقيوده
    القديمة. فتصير القاعدة تدّعي ترقيةً لم تقع، ولا يكتشف المكتب ذلك إلّا حين
    يعجز عن تسجيل زبون باسمه وحده، ولا يفهم لماذا.
    """
    from app import config

    _build_v1_database(config.DB_PATH)
    connection = db.connect(config.DB_PATH)

    real_add_column = migrations._add_column

    def failing_add_column(conn, table, column, definition):
        if column == "insurance_company":
            raise sqlite3.OperationalError("انقطع التيار في منتصف الترقية")
        return real_add_column(conn, table, column, definition)

    monkeypatch.setattr(migrations, "_add_column", failing_add_column)

    with pytest.raises(sqlite3.OperationalError):
        migrations.apply(connection)

    assert migrations.current_version(connection) == 2, "رُفع رقم الإصدار رغم الفشل"
    assert "customers_v3" not in {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }, "بقي الجدول المؤقّت بعد التراجع"

    # وجدول العملاء لم يُمسّ: ما يزال بقيوده القديمة، فالترقية لم تقع فعلاً
    notnull = {row[1] for row in connection.execute("PRAGMA table_info(customers)")
               if row[3]}
    assert "phone" in notnull

    # والتشغيل التالي — بلا العطب — يُكمل الترقية سليمة
    monkeypatch.setattr(migrations, "_add_column", real_add_column)
    migrations.apply(connection)
    assert migrations.current_version(connection) == _latest_version()

    notnull = {row[1] for row in connection.execute("PRAGMA table_info(customers)")
               if row[3]}
    assert "phone" not in notnull
    connection.close()


def test_a_leftover_temporary_table_does_not_block_the_rebuild(app_home):
    """جدول مؤقّت خلّفته نسخة قديمة معطوبة لا يُعدّ دليلَ اكتمال."""
    from app import config

    _build_v1_database(config.DB_PATH)
    connection = db.connect(config.DB_PATH)
    connection.execute("CREATE TABLE customers_v3 (id INTEGER PRIMARY KEY)")

    migrations.apply(connection)

    notnull = {row[1] for row in connection.execute("PRAGMA table_info(customers)")
               if row[3]}
    assert "phone" not in notnull, "لم تُعَد بناء جدول العملاء"
    assert migrations.current_version(connection) == _latest_version()
    connection.close()


def test_foreign_keys_are_restored_after_the_rebuild(app_home):
    """المفاتيح الأجنبية تعود مفعّلة بعد الترقية مهما كان مسارها."""
    from app import config

    _build_v1_database(config.DB_PATH)
    connection = db.connect(config.DB_PATH)
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    migrations.apply(connection)

    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()

# -*- coding: utf-8 -*-
"""ترقية مخطط قاعدة البيانات تدريجياً عبر ``PRAGMA user_version``.

لماذا لا نكتفي بـ ``CREATE TABLE IF NOT EXISTS``؟ لأنّها تنشئ الجداول الناقصة
فقط ولا تضيف **عموداً** جديداً إلى جدول قائم عند صدور نسخة أحدث من البرنامج.
لذلك تُسجَّل كل تغيير في القائمة أدناه، ويطبّق التطبيق ما لم يُطبَّق بعد.

قاعدة الإضافة: لا يُعدَّل تعديلٌ قديم أبداً بعد إطلاقه، بل تُضاف خطوة جديدة.
"""

import pathlib


def _columns(conn, table):
    return {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}


def _add_column(conn, table, column, definition):
    """يضيف عموداً إن لم يكن موجوداً. SQLite لا يعرف ADD COLUMN IF NOT EXISTS."""
    if column not in _columns(conn, table):
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))


def _drop_views(conn):
    """يُسقط كل العروض قبل تطبيق أي ترقية.

    **العروض مشتقّة لا مخزونة**: لا صفّ فيها ولا بيانات، ويُعاد بناؤها كاملةً
    من ``schema.sql`` في كل إقلاع (``db.initialize``). وإسقاطها قبل الترقية
    يزيل صنفاً كاملاً من الأعطال كانت المنظومة قد اصطدمت به مرّتين:

      • **عرضٌ يعترض طريق DDL.** SQLite ترفض ``DROP TABLE`` أو ``RENAME`` ما دام
        عرضٌ قائم يذكر الجدول، فتنهار إعادةُ بناء جدول العملاء برسالة مُضلّلة
        «no such table: main.customers».

      • **عرضٌ من مخطّط الغد فوق جدول اليوم.** ``db.initialize`` ينفّذ
        ``schema.sql`` **قبل** الترقيات، فيُنشأ على قاعدة قديمة عرضٌ يذكر عموداً
        لم يُضَف بعد. وSQLite لا تتحقّق من أعمدة العرض عند إنشائه، لكنّها تتحقّق
        منها عند أول ``DROP TABLE`` بعده — فيُفشل عرضٌ معطوب ترقيةً لا علاقة له
        بها («error in view …: no such column»).

    ولذلك تُسقط هنا **كلّها** لا ما تذكره كل ترقية باسمه: القاعدة العامّة أمتن
    من قائمة تُنسى. والإسقاط يقع داخل معاملة الترقية، فترقيةٌ تتعثّر تُعيد
    العروض كما كانت — DDL في SQLite يتراجع مع المعاملة كالبيانات سواء.
    """
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view'"
    ).fetchall():
        conn.execute('DROP VIEW IF EXISTS "%s"' % row[0])


def _migration_1(conn):
    """الإصدار الأول: المخطط كاملٌ في schema.sql، فلا شيء إضافي هنا."""
    return None


def _migration_2(conn):
    """الحجز المسبق والاحتساب بالساعة.

    1. يُسقط الفهرس القديم الذي كان يمنع أكثر من عقد مفتوح واحد للسيارة.
       سببه أن المكتب محدود عدد السيارات ويحتاج حجزها لعميل قادم قبل إعادتها.
       بديله مشغّلا منع التداخل في schema.sql، وهما يُنشآن مع كل إقلاع.
    2. يضيف أعمدة الاحتساب بالساعة إلى السيارات والعقود.

    ملاحظة: ``ALTER TABLE ADD COLUMN`` في SQLite لا يقبل قيمة افتراضية غير ثابتة،
    ولذلك تُضاف الأعمدة بقيم ثابتة بسيطة ثم تُملأ للصفوف القائمة.
    """
    conn.execute("DROP INDEX IF EXISTS ux_vehicle_open_contract")

    _add_column(conn, "vehicles", "hourly_rate",
                "INTEGER NOT NULL DEFAULT 0")

    _add_column(conn, "contracts", "start_time", "TEXT NOT NULL DEFAULT '12:00'")
    _add_column(conn, "contracts", "actual_end_time", "TEXT")
    _add_column(conn, "contracts", "hourly_rate_snapshot", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "contracts", "billing_mode", "TEXT NOT NULL DEFAULT 'daily'")
    _add_column(conn, "contracts", "hours_count", "INTEGER NOT NULL DEFAULT 0")

    # العروض تُعاد بناؤها لأن v_contracts_full تختار كل أعمدة العقود
    conn.execute("DROP VIEW IF EXISTS v_contracts_full")


def _customers_need_rebuild(conn):
    """هل ما يزال جدول العملاء بقيوده القديمة؟

    يُسأل الجدولُ نفسه لا أثرٌ جانبي: ``PRAGMA table_info`` يُرجع في العمود
    الرابع علم ``NOT NULL``، فوجودُه على أيٍّ من الحقول الثلاثة يعني أن
    البناء لم يتمّ — مهما بقي من جداول مؤقّتة.
    """
    return any(
        row[1] in ("phone", "national_id", "license_number") and row[3]
        for row in conn.execute("PRAGMA table_info(customers)")
    )


def _migration_3(conn):
    """نموذج المكتب وتنبيهات التأمين والعميل السريع.

    1. **تخفيف قيود العملاء.** ``phone`` و``national_id`` و``license_number``
       كانت ``NOT NULL``، فيستحيل تسجيل زبون واقف أمام الموظّف باسمه وحده.
       وSQLite لا يعرف ``ALTER COLUMN DROP NOT NULL``، فالسبيل الوحيد إعادة بناء
       الجدول: جدول جديد بالتعريف المخفَّف ← نسخ الصفوف ← إسقاط القديم ←
       إعادة التسمية.
    2. أعمدة التأمين والفحص الفنّي في السيارات، وهي مصدر التنبيهات.
    3. أعمدة الكفيل في العقود، تطلبها نماذج المكاتب المطبوعة.
    """
    # --- 0) إسقاط العروض أولاً --------------------------------------------
    # **قبل** أي مساس بجدول العملاء: العروض تشير إليه، وSQLite ترفض إسقاطه أو
    # إعادة تسميته ما دام عرضٌ قائم يذكره («error in view v_contracts_full:
    # no such table: main.customers»). ويعيد ``db.initialize`` بناءها بعد
    # الترقية، وكل عباراتها ``IF NOT EXISTS``.
    conn.execute("DROP VIEW IF EXISTS v_contracts_full")
    conn.execute("DROP VIEW IF EXISTS v_contract_balance")

    # --- 1) إعادة بناء جدول العملاء ---------------------------------------
    # المفاتيح الأجنبية مُعطَّلة أثناء الترقية كلّها (انظر ``_apply_one``)،
    # وإلّا اعتبر المحرّك إسقاط الجدول القديم كسراً لمراجع العقود إليه.
    #
    # ومعيار «هل بُنيت؟» هو **قيود الجدول نفسه** لا وجود جدول مؤقّت: وجودُ
    # ``customers_v3`` كان يُعدّ دليلَ اكتمال، فترقيةٌ تعثّرت بعد إنشائه تجعل
    # التشغيل التالي يتخطّى البناء ويرفع رقم الإصدار — فتدّعي القاعدة ترقيةً
    # لم تقع. والجدول المؤقّت يُسقَط أولاً لأن نسخةً قديمة قد تكون خلّفته.
    if _customers_need_rebuild(conn):
        conn.execute("DROP TABLE IF EXISTS customers_v3")
        conn.execute("""
            CREATE TABLE customers_v3 (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name      TEXT    NOT NULL,
                phone          TEXT,
                national_id    TEXT    UNIQUE,
                license_number TEXT,
                license_expiry TEXT,
                nationality    TEXT,
                address        TEXT,
                notes          TEXT,
                is_blacklisted INTEGER NOT NULL DEFAULT 0
                               CHECK (is_blacklisted IN (0, 1)),
                created_at     TEXT NOT NULL
                               DEFAULT (datetime('now', 'localtime')),
                updated_at     TEXT NOT NULL
                               DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            INSERT INTO customers_v3 (id, full_name, phone, national_id,
                                      license_number, license_expiry,
                                      nationality, address, notes,
                                      is_blacklisted, created_at, updated_at)
            SELECT id, full_name, phone, national_id, license_number,
                   license_expiry, nationality, address, notes,
                   is_blacklisted, created_at, updated_at
              FROM customers
        """)
        conn.execute("DROP TABLE customers")
        conn.execute("ALTER TABLE customers_v3 RENAME TO customers")

    # --- 2) التأمين والفحص الفنّي -----------------------------------------
    _add_column(conn, "vehicles", "insurance_company", "TEXT")
    _add_column(conn, "vehicles", "insurance_policy_no", "TEXT")
    _add_column(conn, "vehicles", "insurance_expiry", "TEXT")
    _add_column(conn, "vehicles", "inspection_expiry", "TEXT")

    # --- 3) الكفيل ---------------------------------------------------------
    _add_column(conn, "contracts", "guarantor_name", "TEXT")
    _add_column(conn, "contracts", "guarantor_nationality", "TEXT")
    _add_column(conn, "contracts", "guarantor_passport", "TEXT")
    _add_column(conn, "contracts", "guarantor_address", "TEXT")



# إعادة بناء جدول العملاء تُسقط جدولاً تشير إليه العقود، فتلزم تعطيلُ المفاتيح
# الأجنبية طوال هذه الترقية.
_migration_3.foreign_keys_off = True


def _migration_4(conn):
    """حقول عقد الشركة الرسمي.

    وُضع المخطّط الأول على ما يحتاجه **الحساب**: من استأجر، وأي سيارة، وكم.
    أمّا ورقة العقد الموقَّعة فتطلب أكثر: تاريخ ميلاد المستأجر وجهة إصدار رخصته
    وعنوان عمله، ومكان التجول المسموح به، والضمانات المحجوزة، وحالة السيارة
    ساعةَ خرجت. وهذه ليست زينة: **الورقة هي الحجّة عند الخلاف**، وحقلٌ ناقص
    فيها يعني فراغاً يُملأ بالقلم أو يُترك خالياً.

    كلّها أعمدة تُضاف بلا مساس ببيانات قائمة — ``ALTER TABLE ADD COLUMN`` لا
    يعيد بناء شيء، فبيانات المكتب تبقى كما هي حرفاً بحرف.
    """
    # --- العميل: ما تطلبه ترويسة العقد ---
    _add_column(conn, "customers", "date_of_birth", "TEXT")           # تاريخ الميلاد
    _add_column(conn, "customers", "license_issued_by", "TEXT")       # صادرة عن
    _add_column(conn, "customers", "phone_alt", "TEXT")               # هاتف آخر
    _add_column(conn, "customers", "work_address", "TEXT")            # عنوان العمل
    _add_column(conn, "customers", "blacklist_reason", "TEXT")        # سبب الحظر

    # --- السيارة ---
    _add_column(conn, "vehicles", "body_style", "TEXT")               # التصميم
    _add_column(conn, "vehicles", "license_expiry", "TEXT")           # انتهاء رخصة السيارة

    # --- العقد: بنود الورقة الموقَّعة ---
    _add_column(conn, "contracts", "allowed_area", "TEXT")            # مكان التجول
    _add_column(conn, "contracts", "guarantees", "TEXT")              # الضمانات المحجوزة
    _add_column(conn, "contracts", "departure_condition", "TEXT")     # حالة السيارة عند المغادرة
    _add_column(conn, "contracts", "renewed_until", "TEXT")           # تم تجديد العقد إلى يوم
    _add_column(conn, "contracts", "guarantor_phone", "TEXT")         # هاتف الكفيل
    _add_column(conn, "contracts", "guarantor_work_address", "TEXT")  # عنوان عمل الكفيل

    # --- أثر الإلغاء: يُكتب على الورقة لا في السجلّ وحده ---
    _add_column(conn, "contracts", "cancelled_at", "TEXT")
    _add_column(conn, "contracts", "cancelled_by_name", "TEXT")

    # العرض يختار كل أعمدة العقود والعملاء، فيُعاد بناؤه بالأعمدة الجديدة
    conn.execute("DROP VIEW IF EXISTS v_contracts_full")


def _migration_5(conn):
    """وحدة تحليل ربحية السيارات وعائد الاستثمار.

    المنظومة كانت تعرف كم **دخل** من كل سيارة ولا تعرف كم **خرج** عليها ولا
    بكم اشتُريت، فيتعذّر أن تقول أيّ سيارة تكسب وأيّها حفرة يسقط فيها المال.
    وهذا ما تضيفه هذه الترقية:

      1. ``purchase_price`` و``purchase_date`` في جدول السيارات — رأس المال
         المستثمر، وهو مقام نسبة استرداده.
      2. جدول ``vehicle_expenses`` — دفتر ما يُصرف على السيارة: صيانة وإطارات
         وزيت وتأمين وغيرها.

    **غير هدّامة بالتعريف**: ``ALTER TABLE ADD COLUMN`` لا يعيد بناء جدولاً،
    و``CREATE TABLE IF NOT EXISTS`` لا يمسّ جدولاً قائماً. فلا يُحذف صفٌّ ولا
    يتغيّر معرّف، وبيانات المكتب بعدها هي بيانات المكتب قبلها حرفاً بحرف.

    ولا قيمة افتراضية لثمن الشراء عمداً: ``NULL`` تعني «لا يعرف المكتب الثمن»،
    وصفرٌ يعني «كلّفت صفراً» — والفرق بينهما نسبةُ عائدٍ صحيحة ونسبةٌ كاذبة.
    """
    _add_column(conn, "vehicles", "purchase_price", "INTEGER")
    _add_column(conn, "vehicles", "purchase_date", "TEXT")

    # المفتاح الأجنبي على العملات يبقى معطَّلاً عن جداول قديمة؟ لا: الجدول
    # جديد كلّه، ويُنشأ بقيوده كاملة كما في schema.sql حرفاً بحرف.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_expenses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id    INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
            expense_type  TEXT    NOT NULL DEFAULT 'other'
                                  CHECK (expense_type IN ('maintenance', 'tyres', 'oil',
                                                          'insurance', 'other')),
            amount        INTEGER NOT NULL CHECK (amount >= 0),
            currency_code TEXT    NOT NULL REFERENCES currencies (code),
            rate_to_base  INTEGER NOT NULL DEFAULT 1000000 CHECK (rate_to_base > 0),
            date          TEXT    NOT NULL,
            notes         TEXT,
            created_by    INTEGER REFERENCES users (id),
            created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_expenses_vehicle ON vehicle_expenses (vehicle_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_expenses_date ON vehicle_expenses (date)"
    )


# (رقم الإصدار، الدالة) بترتيب تصاعدي
MIGRATIONS = [
    (1, _migration_1),
    (2, _migration_2),
    (3, _migration_3),
    (4, _migration_4),
    (5, _migration_5),
]


def current_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _apply_one(conn, target, migrate):
    """يطبّق ترقيةً واحدة **ورقمَها** في معاملة واحدة.

    الذرّية هنا ليست ترفاً: ترقيةٌ تتعثّر في منتصفها — انقطاع تيار، قرص ممتلئ،
    مضادّ فيروسات — كانت تترك القاعدة نصف مبنيّة ورقمَ إصدارها يدّعي الاكتمال.
    فإمّا أن تتمّ الترقية ورقمُها معاً، وإمّا ألّا يقع منها شيء ويُعاد التشغيل.

    و``PRAGMA foreign_keys`` لا يعمل داخل معاملة، فيُضبط قبل ``BEGIN`` ويُعاد
    بعد نهايتها — وترقيةٌ تُعيد بناء جدول مرجعيّ تطلب تعطيله بعلمٍ عليها.
    """
    needs_fk_off = getattr(migrate, "foreign_keys_off", False)
    previous_fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    if needs_fk_off:
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _drop_views(conn)
            migrate(conn)
            # PRAGMA لا يقبل المعاملات (parameters)، والقيمة رقم مُولَّد داخلياً.
            # وهو جزء من ترويسة القاعدة، فيتراجع مع المعاملة كبقيّة التغييرات.
            conn.execute("PRAGMA user_version = %d" % int(target))
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        if needs_fk_off:
            conn.execute("PRAGMA foreign_keys = %s" % ("ON" if previous_fk else "OFF"))


# اسم نسخة ما قبل الترقية. ثابتٌ هنا فيجده دليل الترقية ويجده المستخدم.
PRE_UPGRADE_PREFIX = "before-upgrade"


def backup_before_upgrade(conn):
    """ينسخ قاعدة البيانات قبل أوّل ترقية تُطبَّق عليها، ويُرجع مسار النسخة.

    **هذه هي الضمانة التي تُسلَّم للعميل مع التحديث.** الترقيات نفسها لا تحذف
    شيئاً — ``ALTER TABLE ADD COLUMN`` لا يعيد بناء جدول — لكن بين «مصمَّمة
    ألّا تُتلف» و«يمكن الرجوع لو أتلفت» فرقٌ يساوي شهور عمل مكتب.

    والنسخة تُؤخذ **مرّةً واحدة** حين يكون هناك ما يُرقّى فعلاً: أخذُها في كل
    إقلاع يملأ قرص المكتب بنسخ متطابقة.

    يُرجع ``None`` حين لا شيء يُرقّى، أو حين تتعذّر النسخة — وتعذّرها لا يوقف
    الترقية: تحديثٌ يرفض أن يبدأ لأن القرص ممتلئ يترك المكتب بلا منظومة أصلاً.
    """
    import datetime
    import shutil

    from .. import config

    if current_version(conn) >= max(number for number, _ in MIGRATIONS):
        return None

    source = pathlib.Path(config.DB_PATH)
    if not source.is_file():
        return None                      # قاعدة جديدة: لا شيء يُنسخ

    try:
        # تُفرَّغ سجلّات WAL في الملف الأصلي قبل نسخه، وإلّا نُسخت قاعدة تنقصها
        # آخر المعاملات — وهي أهمّها: أحدث ما كتبه المكتب.
        conn.execute("PRAGMA wal_checkpoint(FULL)")

        destination = pathlib.Path(config.BACKUP_DIR) / (
            "%s-v%d-%s.db" % (PRE_UPGRADE_PREFIX, current_version(conn),
                              datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination
    except Exception:
        return None


def apply(conn):
    """يطبّق كل الترقيات الأحدث من الإصدار المخزَّن، ويُرجع الإصدار النهائي."""
    version = current_version(conn)
    backup_before_upgrade(conn)

    for target, migrate in MIGRATIONS:
        if target <= version:
            continue
        _apply_one(conn, target, migrate)
        version = target

    return version

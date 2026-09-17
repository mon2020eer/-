-- =============================================================================
--  مخطط قاعدة بيانات منظومة إدارة مكتب إيجار السيارات
--
--  قواعد عامّة اعتُمدت في كامل المخطط:
--    • كل المبالغ المالية أعداد صحيحة بالوحدة الصغرى للعملة (درهم/سنت)،
--      تفادياً لأخطاء تقريب الفاصلة العائمة في الحسابات المالية.
--    • كل التواريخ نصوص بصيغة YYYY-MM-DD، وكل الأوقات YYYY-MM-DD HH:MM:SS.
--    • حالة الدفع لا تُخزَّن بل تُشتَقّ من مجموع الدفعات (انظر v_contract_balance).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- العملات: العملة الأساس واحدة، وبقيّة العملات تُنسب إليها بسعر صرف قابل للتحديث
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS currencies (
    code         TEXT PRIMARY KEY,                    -- LYD / USD / EUR
    name_ar      TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    decimals     INTEGER NOT NULL DEFAULT 2 CHECK (decimals BETWEEN 0 AND 3),
    -- سعر صرف وحدة واحدة من هذه العملة مقابل العملة الأساس، مضروباً في 1,000,000
    -- (تخزين صحيح لتفادي الفاصلة العائمة: 5.25 دينار للدولار ← 5250000)
    rate_to_base INTEGER NOT NULL DEFAULT 1000000 CHECK (rate_to_base > 0),
    is_base      INTEGER NOT NULL DEFAULT 0 CHECK (is_base IN (0, 1)),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -----------------------------------------------------------------------------
-- المستخدمون والأدوار
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT    NOT NULL UNIQUE,
    full_name            TEXT    NOT NULL,
    password_hash        TEXT    NOT NULL,
    role                 TEXT    NOT NULL CHECK (role IN ('admin', 'staff')),
    phone                TEXT,
    is_active            INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    last_login_at        TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -----------------------------------------------------------------------------
-- العملاء ومرفقاتهم
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name      TEXT    NOT NULL,
    -- الهاتف والرقم الوطني والرخصة اختيارية عمداً: المكتب يستقبل زبوناً واقفاً
    -- أمامه فيكتب اسمه ويفتح العقد، ثم يُكمل وثائقه. والمنظومة تَسِم الناقص
    -- بشارة «بيانات ناقصة» وتُلحّ عليه بدل أن تمنع العمل.
    phone          TEXT,
    national_id    TEXT    UNIQUE,                    -- رقم الجواز أو الرقم الوطني
    license_number TEXT,
    license_expiry TEXT,                              -- YYYY-MM-DD
    nationality    TEXT,
    address        TEXT,
    notes          TEXT,
    is_blacklisted INTEGER NOT NULL DEFAULT 0 CHECK (is_blacklisted IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS customer_attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    file_name   TEXT    NOT NULL,
    stored_path TEXT    NOT NULL,                     -- نسخة داخل مجلد بيانات التطبيق
    kind        TEXT    NOT NULL DEFAULT 'other'
                        CHECK (kind IN ('id', 'license', 'passport', 'contract', 'other')),
    note        TEXT,
    uploaded_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -----------------------------------------------------------------------------
-- السيارات
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vehicles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    brand         TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    year          INTEGER NOT NULL CHECK (year BETWEEN 1950 AND 2100),
    plate_number  TEXT    NOT NULL UNIQUE,
    color         TEXT    NOT NULL,
    daily_rate    INTEGER NOT NULL CHECK (daily_rate >= 0),
    weekly_rate   INTEGER NOT NULL DEFAULT 0 CHECK (weekly_rate >= 0),  -- 0 = لا سعر أسبوعي
    -- سعر الساعة للإرجاع المبكّر. 0 = يُحتسب تلقائياً من السعر اليومي ÷ 24
    hourly_rate   INTEGER NOT NULL DEFAULT 0 CHECK (hourly_rate >= 0),
    currency_code TEXT    NOT NULL REFERENCES currencies (code),
    status        TEXT    NOT NULL DEFAULT 'available'
                          CHECK (status IN ('available', 'rented', 'maintenance')),
    odometer      INTEGER NOT NULL DEFAULT 0 CHECK (odometer >= 0),
    chassis_number TEXT,
    insurance_company   TEXT,
    insurance_policy_no TEXT,
    insurance_expiry    TEXT,                         -- YYYY-MM-DD
    inspection_expiry   TEXT,                         -- الفحص الفنّي، YYYY-MM-DD
    notes         TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -----------------------------------------------------------------------------
-- عقود الإيجار
--
--  لقطات الأسعار (snapshot) تُحفظ داخل العقد فلا تتأثّر العقود القديمة بأي
--  تعديل لاحق على تعرفة السيارة أو على سعر صرف العملة.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_number     TEXT    NOT NULL UNIQUE,      -- CR-2026-0001
    customer_id         INTEGER NOT NULL REFERENCES customers (id),
    vehicle_id          INTEGER NOT NULL REFERENCES vehicles (id),

    start_date          TEXT    NOT NULL,             -- YYYY-MM-DD
    expected_end_date   TEXT    NOT NULL,
    actual_end_date     TEXT,
    -- أوقات الاستلام والتسليم (HH:MM): تلزم عند الاحتساب بالساعة
    start_time          TEXT    NOT NULL DEFAULT '12:00',
    actual_end_time     TEXT,

    daily_rate_snapshot  INTEGER NOT NULL CHECK (daily_rate_snapshot >= 0),
    weekly_rate_snapshot INTEGER NOT NULL DEFAULT 0 CHECK (weekly_rate_snapshot >= 0),
    hourly_rate_snapshot INTEGER NOT NULL DEFAULT 0 CHECK (hourly_rate_snapshot >= 0),
    currency_code        TEXT    NOT NULL REFERENCES currencies (code),
    rate_to_base         INTEGER NOT NULL CHECK (rate_to_base > 0),

    -- طريقة الاحتساب النهائية: بالأيام، أو بالأيام والساعات عند الإرجاع المبكّر
    billing_mode        TEXT    NOT NULL DEFAULT 'daily'
                                CHECK (billing_mode IN ('daily', 'hourly')),
    hours_count         INTEGER NOT NULL DEFAULT 0 CHECK (hours_count >= 0),
    days_count          INTEGER NOT NULL CHECK (days_count >= 1),
    subtotal            INTEGER NOT NULL CHECK (subtotal >= 0),
    discount            INTEGER NOT NULL DEFAULT 0 CHECK (discount >= 0),
    extra_charges       INTEGER NOT NULL DEFAULT 0 CHECK (extra_charges >= 0),
    total_amount        INTEGER NOT NULL CHECK (total_amount >= 0),

    start_odometer      INTEGER,
    end_odometer        INTEGER,
    pickup_location     TEXT,
    return_location     TEXT,

    status              TEXT    NOT NULL DEFAULT 'open'
                                CHECK (status IN ('open', 'closed', 'cancelled')),
    notes               TEXT,

    -- بيانات الكفيل: تطلبها نماذج عقود المكاتب المطبوعة ولا مقابل لها في
    -- المنظومة، فتُخزَّن في العقد لا في العميل لأن الكفيل يتغيّر بين عقد وآخر.
    guarantor_name        TEXT,
    guarantor_nationality TEXT,
    guarantor_passport    TEXT,
    guarantor_address     TEXT,

    created_by          INTEGER NOT NULL REFERENCES users (id),
    closed_by           INTEGER REFERENCES users (id),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at           TEXT,

    CHECK (expected_end_date >= start_date),
    CHECK (actual_end_date IS NULL OR actual_end_date >= start_date)
);

-- -----------------------------------------------------------------------------
-- الدفعات: تسمح بعربون ثمّ دفعات جزئية متتابعة على العقد الواحد
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL REFERENCES contracts (id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL CHECK (amount > 0),
    method      TEXT    NOT NULL DEFAULT 'cash'
                        CHECK (method IN ('cash', 'bank', 'card', 'other')),
    kind        TEXT    NOT NULL DEFAULT 'payment'
                        CHECK (kind IN ('deposit', 'payment', 'refund')),
    paid_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    reference   TEXT,
    note        TEXT,
    recorded_by INTEGER NOT NULL REFERENCES users (id)
);

-- -----------------------------------------------------------------------------
-- الصيانة: فتح سجلّ صيانة ينقل السيارة تلقائياً إلى حالة «صيانة» (طبقة الخدمة)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS maintenance_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id    INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    started_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    finished_at   TEXT,
    cost          INTEGER NOT NULL DEFAULT 0 CHECK (cost >= 0),
    currency_code TEXT    NOT NULL REFERENCES currencies (code),
    kind          TEXT    NOT NULL DEFAULT 'repair'
                          CHECK (kind IN ('periodic', 'repair', 'accident', 'other')),
    description   TEXT    NOT NULL,
    workshop      TEXT,
    odometer      INTEGER,
    created_by    INTEGER REFERENCES users (id)
);

-- -----------------------------------------------------------------------------
-- المخالفات المرورية المرصودة أثناء فترة الإيجار
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS violations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id            INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    contract_id           INTEGER REFERENCES contracts (id) ON DELETE SET NULL,
    occurred_at           TEXT    NOT NULL,
    amount                INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    currency_code         TEXT    NOT NULL REFERENCES currencies (code),
    description           TEXT    NOT NULL,
    reference             TEXT,
    is_charged_to_customer INTEGER NOT NULL DEFAULT 1 CHECK (is_charged_to_customer IN (0, 1)),
    is_settled            INTEGER NOT NULL DEFAULT 0 CHECK (is_settled IN (0, 1)),
    created_by            INTEGER REFERENCES users (id),
    created_at            TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -----------------------------------------------------------------------------
-- سجلّ النسخ الاحتياطي إلى Google Drive
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backup_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    finished_at   TEXT,
    mode          TEXT    NOT NULL CHECK (mode IN ('auto', 'manual', 'restore')),
    status        TEXT    NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'success', 'failed')),
    file_name     TEXT,
    file_size     INTEGER,
    drive_file_id TEXT,
    message       TEXT,
    triggered_by  INTEGER REFERENCES users (id)
);

-- -----------------------------------------------------------------------------
-- سجلّ التدقيق: من فعل ماذا ومتى
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users (id),
    username   TEXT,                                  -- يُنسخ نصّاً فيبقى بعد حذف المستخدم
    action     TEXT    NOT NULL,                      -- create / update / delete / login …
    entity     TEXT    NOT NULL,                      -- customer / vehicle / contract …
    entity_id  INTEGER,
    details    TEXT,                                  -- JSON
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -----------------------------------------------------------------------------
-- إعدادات التطبيق: مفتاح/قيمة
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- =============================================================================
--  الفهارس
-- =============================================================================

CREATE INDEX IF NOT EXISTS ix_contracts_customer   ON contracts (customer_id);
CREATE INDEX IF NOT EXISTS ix_contracts_period
    ON contracts (vehicle_id, start_date, expected_end_date);
CREATE INDEX IF NOT EXISTS ix_contracts_vehicle    ON contracts (vehicle_id);
CREATE INDEX IF NOT EXISTS ix_contracts_status     ON contracts (status, start_date);
CREATE INDEX IF NOT EXISTS ix_contracts_start      ON contracts (start_date);
CREATE INDEX IF NOT EXISTS ix_payments_contract    ON payments (contract_id);
CREATE INDEX IF NOT EXISTS ix_payments_paid_at     ON payments (paid_at);
CREATE INDEX IF NOT EXISTS ix_vehicles_plate       ON vehicles (plate_number);
CREATE INDEX IF NOT EXISTS ix_vehicles_status      ON vehicles (status);
CREATE INDEX IF NOT EXISTS ix_customers_phone      ON customers (phone);
CREATE INDEX IF NOT EXISTS ix_customers_name       ON customers (full_name);
CREATE INDEX IF NOT EXISTS ix_maintenance_vehicle  ON maintenance_records (vehicle_id);
CREATE INDEX IF NOT EXISTS ix_violations_vehicle   ON violations (vehicle_id);
CREATE INDEX IF NOT EXISTS ix_audit_created        ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS ix_attachments_customer ON customer_attachments (customer_id);

-- =============================================================================
--  العروض (Views)
-- =============================================================================

-- رصيد العقد: المدفوع والمتبقّي وحالة الدفع، محسوبة اشتقاقاً من جدول الدفعات
-- فلا يمكن أن تتناقض حالة الدفع مع الدفعات المسجّلة فعلاً.
CREATE VIEW IF NOT EXISTS v_contract_balance AS
SELECT
    c.id                                                          AS contract_id,
    c.total_amount                                                AS total_amount,
    COALESCE(SUM(CASE WHEN p.kind = 'refund' THEN -p.amount
                      ELSE p.amount END), 0)                      AS paid_amount,
    c.total_amount - COALESCE(SUM(CASE WHEN p.kind = 'refund' THEN -p.amount
                                       ELSE p.amount END), 0)     AS balance_due,
    CASE
        WHEN COALESCE(SUM(CASE WHEN p.kind = 'refund' THEN -p.amount
                               ELSE p.amount END), 0) >= c.total_amount THEN 'paid'
        WHEN COALESCE(SUM(CASE WHEN p.kind = 'refund' THEN -p.amount
                               ELSE p.amount END), 0) > 0              THEN 'deposit'
        ELSE 'due'
    END                                                           AS payment_status
FROM contracts c
LEFT JOIN payments p ON p.contract_id = c.id
GROUP BY c.id;

-- عرض العقود موسّعاً بأسماء العميل والسيارة وحالة الدفع — يخدم جدول العقود والبحث
CREATE VIEW IF NOT EXISTS v_contracts_full AS
SELECT
    c.*,
    cu.full_name                                   AS customer_name,
    cu.phone                                       AS customer_phone,
    cu.national_id                                 AS customer_national_id,
    -- بقيّة بيانات العميل والسيارة: يحتاجها ملء نموذج عقد المكتب، وجلبها هنا
    -- يوفّر استعلامين إضافيين لكل طباعة.
    cu.nationality                                 AS customer_nationality,
    cu.license_number                              AS customer_license_number,
    cu.license_expiry                              AS customer_license_expiry,
    cu.address                                     AS customer_address,
    v.plate_number                                 AS plate_number,
    v.brand                                        AS brand,
    v.model                                        AS model,
    v.year                                         AS year,
    v.color                                        AS color,
    v.chassis_number                               AS chassis_number,
    v.brand || ' ' || v.model                      AS vehicle_title,
    b.paid_amount                                  AS paid_amount,
    b.balance_due                                  AS balance_due,
    b.payment_status                               AS payment_status,
    u.full_name                                    AS created_by_name
FROM contracts c
JOIN customers          cu ON cu.id = c.customer_id
JOIN vehicles           v  ON v.id  = c.vehicle_id
JOIN v_contract_balance b  ON b.contract_id = c.id
LEFT JOIN users         u  ON u.id  = c.created_by;

-- =============================================================================
--  المشغّلات (Triggers): تحديث حقل updated_at تلقائياً
-- =============================================================================
CREATE TRIGGER IF NOT EXISTS trg_customers_updated
AFTER UPDATE ON customers FOR EACH ROW
BEGIN
    UPDATE customers SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_vehicles_updated
AFTER UPDATE ON vehicles FOR EACH ROW
BEGIN
    UPDATE vehicles SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_users_updated
AFTER UPDATE ON users FOR EACH ROW
BEGIN
    UPDATE users SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- =============================================================================
--  الضمانة الجوهرية: منع تداخل فترات التأجير
--
--  المكتب محدود عدد السيارات، فيحتاج أن يحجز السيارة نفسها لعميل قادم قبل أن
--  يُعيدها العميل الحالي. ولذلك لا يُمنع تعدّد العقود المفتوحة على السيارة، بل
--  يُمنع ما هو خطأ فعلاً: **تأجير السيارة نفسها لعميلين في الأيام نفسها**.
--
--  لماذا مشغّل لا فهرس فريد؟ لأن «عدم تداخل المدد» شرط بين صفّين لا يمكن التعبير
--  عنه بفهرس. المشغّل يجعل الضمانة داخل محرّك SQLite نفسه، فيرفض الإدراج المتداخل
--  حتى لو جاء بـ SQL خام يتجاوز طبقة الخدمة كلّها.
--
--  فترة الشغل نصف مفتوحة: [start_date, end_date) حيث
--      end_date = COALESCE(actual_end_date, expected_end_date)
--  ويُرفع إلى اليوم التالي للبداية إن تساويا (عقد اليوم الواحد يشغل يومه).
--
--  **يوم التسليم يوم تسليم مشترك**: من يُعيد السيارة يوم 5 تستطيع تسليمها لعميل
--  آخر في اليوم نفسه، وهو عين ما يفعله المكتب فعلاً. ولذلك شرط التداخل صارم
--  (<) لا متساهل (<=)، وإلّا لتعذّر تجديد العقد أو تسليم السيارة لعميل تالٍ.
--
--  العقود الملغاة لا تحجز شيئاً، فتُستثنى.
-- =============================================================================
CREATE TRIGGER IF NOT EXISTS trg_contracts_no_overlap_insert
BEFORE INSERT ON contracts FOR EACH ROW
WHEN NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM contracts c
     WHERE c.vehicle_id = NEW.vehicle_id
       AND c.status <> 'cancelled'
       AND c.start_date < MAX(COALESCE(NEW.actual_end_date, NEW.expected_end_date),
                              date(NEW.start_date, '+1 day'))
       AND NEW.start_date < MAX(COALESCE(c.actual_end_date, c.expected_end_date),
                                date(c.start_date, '+1 day'))
)
BEGIN
    SELECT RAISE(ABORT, 'contract_period_overlap');
END;

CREATE TRIGGER IF NOT EXISTS trg_contracts_no_overlap_update
BEFORE UPDATE OF vehicle_id, start_date, expected_end_date, actual_end_date, status
ON contracts FOR EACH ROW
WHEN NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM contracts c
     WHERE c.vehicle_id = NEW.vehicle_id
       AND c.id <> NEW.id
       AND c.status <> 'cancelled'
       AND c.start_date < MAX(COALESCE(NEW.actual_end_date, NEW.expected_end_date),
                              date(NEW.start_date, '+1 day'))
       AND NEW.start_date < MAX(COALESCE(c.actual_end_date, c.expected_end_date),
                                date(c.start_date, '+1 day'))
)
BEGIN
    SELECT RAISE(ABORT, 'contract_period_overlap');
END;

# -*- coding: utf-8 -*-
"""إعدادات التطبيق ومساراته.

كل ما يكتبه التطبيق أثناء التشغيل (قاعدة البيانات، المرفقات، سجلّات التشغيل،
بيانات اعتماد Google) يُوضع في مجلد بيانات المستخدم لا بجوار ملف البرنامج،
لأن مجلد ``Program Files`` في ويندوز غير قابل للكتابة للمستخدم العادي، ولأن
ذلك يُبقي البيانات سليمة عند تحديث التطبيق أو إعادة تثبيته.

مسار البيانات:
    ويندوز : %APPDATA%\\CarRentalOffice
    لينكس  : ~/.local/share/CarRentalOffice        (للتطوير والاختبار)

يمكن تجاوز المسار بمتغيّر البيئة ``CAR_RENTAL_HOME``، وهو ما تستخدمه
الاختبارات لتعمل على مجلد مؤقّت معزول.
"""

import os
import pathlib
import sys

APP_NAME = "CarRentalOffice"
APP_TITLE_AR = "منظومة إدارة مكتب إيجار السيارات"
APP_VERSION = "1.0.0"

# رقم إصدار المخطط: يزيد مع كل ترقية في migrations.py
SCHEMA_VERSION = 1


def _default_home():
    override = os.environ.get("CAR_RENTAL_HOME")
    if override:
        return pathlib.Path(override).expanduser()

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (pathlib.Path.home() / "AppData" / "Roaming")
        return pathlib.Path(base) / APP_NAME

    return pathlib.Path.home() / ".local" / "share" / APP_NAME


DATA_DIR = _default_home()
DB_PATH = DATA_DIR / "car_rental.db"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
BACKUP_DIR = DATA_DIR / "backups"          # النسخ المحلية المؤقتة قبل الرفع
EXPORTS_DIR = DATA_DIR / "exports"         # ملفات PDF و CSV المولَّدة
TEMPLATES_DIR = DATA_DIR / "templates"     # نماذج عقود المكاتب المرفوعة
LOG_PATH = DATA_DIR / "app.log"

# بيانات اعتماد Google التي ينزّلها المالك من Google Cloud Console
GOOGLE_CREDENTIALS_PATH = DATA_DIR / "credentials.json"
GOOGLE_TOKEN_PATH = DATA_DIR / "token.json"

DRIVE_FOLDER_NAME = "CarRental_Backups"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# حساب المدير الأول الذي يُنشأ عند أول تشغيل، مع إلزام تغيير كلمة المرور فوراً
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

# سياسة الدخول
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 10
MIN_PASSWORD_LENGTH = 8

# الافتراضات القابلة للتعديل من شاشة الإعدادات
# القيم الافتراضية تُزرع بـ ``ON CONFLICT DO NOTHING``: تُكتب مرّةً واحدة على
# قاعدة جديدة، ولا تمسّ ما ضبطه مكتبٌ قائم مهما تغيّرت هنا.
DEFAULT_SETTINGS = {
    "office_name": "شركة المسار المتحد",
    "office_phone": "",
    "office_phone_alt": "",
    "office_address": "",
    "commercial_register": "",
    "office_logo": "",
    "base_currency": "LYD",
    "backup_enabled": "1",
    "backup_retention": "30",
    "auto_backup_daily": "1",
    "last_backup_at": "",
    "drive_folder_id": "",
}

ROLE_LABELS = {"admin": "مدير", "staff": "موظّف"}

VEHICLE_STATUS_LABELS = {
    "available": "متاحة",
    "rented": "مؤجَّرة",
    "maintenance": "في الصيانة",
}

CONTRACT_STATUS_LABELS = {
    "open": "مفتوح",
    "closed": "مُغلق",
    "cancelled": "مُلغى",
}

PAYMENT_STATUS_LABELS = {
    "paid": "مدفوع بالكامل",
    "deposit": "عربون / دفعة جزئية",
    "due": "غير مدفوع",
}

PAYMENT_METHOD_LABELS = {
    "cash": "نقداً",
    "bank": "حوالة مصرفية",
    "card": "بطاقة",
    "other": "أخرى",
}

MAINTENANCE_KIND_LABELS = {
    "periodic": "صيانة دورية",
    "repair": "إصلاح عطل",
    "accident": "حادث",
    "other": "أخرى",
}


def reload_paths():
    """يعيد حساب المسارات من متغيّر البيئة ``CAR_RENTAL_HOME``.

    تستدعيه الاختبارات بعد توجيه المسار إلى مجلد مؤقّت، فلا تلمس بيانات
    التشغيل الحقيقية إطلاقاً.
    """
    global DATA_DIR, DB_PATH, ATTACHMENTS_DIR, BACKUP_DIR, EXPORTS_DIR, LOG_PATH
    global TEMPLATES_DIR
    global GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

    DATA_DIR = _default_home()
    DB_PATH = DATA_DIR / "car_rental.db"
    ATTACHMENTS_DIR = DATA_DIR / "attachments"
    BACKUP_DIR = DATA_DIR / "backups"
    EXPORTS_DIR = DATA_DIR / "exports"
    TEMPLATES_DIR = DATA_DIR / "templates"
    LOG_PATH = DATA_DIR / "app.log"
    GOOGLE_CREDENTIALS_PATH = DATA_DIR / "credentials.json"
    GOOGLE_TOKEN_PATH = DATA_DIR / "token.json"
    return DATA_DIR


def ensure_directories():
    """ينشئ مجلدات البيانات إن لم تكن موجودة. يُستدعى قبل أي عملية كتابة."""
    for directory in (DATA_DIR, ATTACHMENTS_DIR, BACKUP_DIR, EXPORTS_DIR,
                      TEMPLATES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

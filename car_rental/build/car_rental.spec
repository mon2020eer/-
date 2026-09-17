# -*- mode: python ; coding: utf-8 -*-
"""ملف مواصفات PyInstaller لبناء نسخة ويندوز التنفيذية.

وضع البناء: ``onedir`` (مجلد لا ملف واحد) وهو الخيار المقصود:
  • بدء التشغيل أسرع بكثير، لأن ``onefile`` يفكّ ضغط كل شيء إلى مجلد مؤقّت
    في كل تشغيل.
  • إنذارات مضادات الفيروسات الكاذبة أقلّ بكثير مع ``onedir``.
  • تحديث ملف واحد لاحقاً ممكن دون إعادة بناء كل شيء.

التشغيل من مجلد المشروع:
    pyinstaller build/car_rental.spec --noconfirm
"""

import pathlib

PROJECT_DIR = pathlib.Path(SPECPATH).parent
APP_DIR = PROJECT_DIR / "app"

block_cipher = None

a = Analysis(
    # نقطة الدخول `run.py` لا `app/__main__.py`: PyInstaller تشغّل ملف نقطة
    # الدخول بلا سياق حزمة، فتسقط استيرادات `app/__main__.py` النسبية بـ
    # «attempted relative import with no known parent package».
    [str(PROJECT_DIR / "run.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    # ملفات غير برمجية يحتاجها التطبيق وقت التشغيل
    datas=[
        (str(APP_DIR / "core" / "schema.sql"), "app/core"),
        (str(APP_DIR / "ui" / "theme.qss"), "app/ui"),
    ],
    # وحدات تُستورد ديناميكياً فلا يكتشفها التحليل الساكن
    hiddenimports=[
        "googleapiclient.discovery",
        "google_auth_oauthlib.flow",
        "google.auth.transport.requests",
        "google.oauth2.credentials",
        # التحقّق من توقيع مفتاح الاشتراك: تُستورد داخل الدوال لا في رأس الوحدة
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.primitives.serialization",
    ],
    hookspath=[],
    runtime_hooks=[],
    # استبعاد وحدات Qt الثقيلة غير المستخدمة: يقلّص الحجم عشرات الميغابايتات
    excludes=[
        "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets", "PyQt6.QtMultimedia", "PyQt6.QtBluetooth",
        "PyQt6.QtNetworkAuth", "PyQt6.QtPositioning", "PyQt6.QtSensors",
        "PyQt6.QtSerialPort", "PyQt6.QtTest", "PyQt6.Qt3DCore",
        "tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CarRentalOffice",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX يرفع احتمال الإنذار الكاذب من مضادات الفيروسات
    console=False,             # تطبيق نافذي: لا تظهر نافذة أوامر سوداء
    disable_windowed_traceback=False,
    icon=None,                 # ضع هنا مسار ملف .ico إن توفّر شعار للمكتب
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="CarRentalOffice",
)

# -*- coding: utf-8 -*-
"""نقطة تشغيل منظومة إدارة مكتب إيجار السيارات.

التشغيل:
    python -m app                  التشغيل المعتاد
    python -m app --self-test      فحص ذاتي بلا شاشة: يبني الواجهات ويغلقها
    python -m app --backup-now     نسخة احتياطية من سطر الأوامر (لمهمّة مجدولة)
    python -m app --data-dir PATH  تشغيل على مجلد بيانات مختلف

ترتيب الإقلاع: تجهيز المجلدات ← تهيئة قاعدة البيانات ← ضبط الواجهة العربية
← شاشة الدخول ← النافذة الرئيسية.
"""

import argparse
import os
import sys
import traceback


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="car-rental", description="منظومة إدارة مكتب إيجار السيارات"
    )
    parser.add_argument("--self-test", action="store_true",
                        help="فحص ذاتي بلا واجهة رسومية ظاهرة")
    parser.add_argument("--backup-now", action="store_true",
                        help="تنفيذ نسخة احتياطية ثم الخروج")
    parser.add_argument("--data-dir", default=None,
                        help="مسار مجلد البيانات (يتجاوز الافتراضي)")
    parser.add_argument("--version", action="store_true", help="عرض رقم الإصدار")
    return parser.parse_args(argv)


def _bootstrap(data_dir=None):
    """يجهّز المسارات وقاعدة البيانات. يُرجع وحدة الإعدادات بعد التحديث."""
    if data_dir:
        os.environ["CAR_RENTAL_HOME"] = str(data_dir)

    from . import config
    from .core import db

    config.reload_paths()
    config.ensure_directories()
    db.initialize()

    # مرور الوقت وحده يغيّر حالة الأسطول: حجز الغد يصير إيجار اليوم، وعقد انتهى
    # أمس يترك سيارته متاحة — وقد يقع ذلك والتطبيق مغلق.
    from .repositories import vehicles_repo

    vehicles_repo.sync_all_statuses()
    return config


def run_gui(self_test=False):
    """يشغّل الواجهة الرسومية ويُرجع رمز الخروج."""
    from PyQt6.QtWidgets import QApplication

    from .ui import rtl
    from .ui.login_window import LoginWindow
    from .ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    rtl.apply(app)

    state = {"main_window": None}

    login = LoginWindow()

    def on_login(user):
        window = MainWindow(user)
        state["main_window"] = window
        login.close()
        window.show()

    login.logged_in.connect(on_login)
    login.show()

    if self_test:
        # فحص ذاتي: نبني النافذة الرئيسية بحساب وهمي ثم نخرج فوراً.
        from .core import session
        from .repositories import users_repo

        row = users_repo.get_by_username("admin")
        user = session.login(session.CurrentUser.from_row(row))
        window = MainWindow(user)
        window.show()
        app.processEvents()
        window.close()
        login.close()
        return 0

    return app.exec()


def run_backup():
    """نسخة احتياطية من سطر الأوامر — تصلح لمهمّة مجدولة في ويندوز."""
    from .core import session
    from .repositories import users_repo
    from .services.backup import backup_service

    row = users_repo.get_by_username("admin")
    if row is not None:
        session.login(session.CurrentUser.from_row(row))

    try:
        result = backup_service.run_backup(mode="auto")
    except Exception as error:
        sys.stderr.write("فشل النسخ الاحتياطي: %s\n" % error)
        return 1

    sys.stdout.write("تمت النسخة الاحتياطية: %s\n" % result.get("file_name"))
    return 0


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        from . import config

        sys.stdout.write("%s — الإصدار %s\n" % (config.APP_TITLE_AR, config.APP_VERSION))
        return 0

    try:
        _bootstrap(args.data_dir)
    except Exception as error:
        sys.stderr.write("تعذّرت تهيئة قاعدة البيانات: %s\n%s\n"
                         % (error, traceback.format_exc()))
        return 1

    if args.backup_now:
        return run_backup()

    if args.self_test:
        # منصّة بلا شاشة: تسمح بفحص الواجهة في بيئات البناء والاختبار
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    return run_gui(self_test=args.self_test)


if __name__ == "__main__":
    sys.exit(main())

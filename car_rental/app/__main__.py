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
import datetime
import os
import sys
import traceback


# ---------------------------------------------------------------------------
# مخارج آمنة
# ---------------------------------------------------------------------------
# في نسخة **نافذية** (console=False) يجعل ويندوز ``sys.stdout`` و``sys.stderr``
# قيمتهما ``None``. فالكتابة عليهما مباشرةً تُسقط البرنامج بـ
# «'NoneType' object has no attribute 'write'» — وهو ما وقع فعلاً، فأخفى
# السببَ الحقيقي للفشل خلف رسالة لا تدلّ على شيء.
def _write(stream, text):
    """يكتب على مجرى قد يكون غائباً، ولا يُسقط البرنامج إن غاب."""
    if stream is None:
        return False
    try:
        stream.write(text)
        stream.flush()
        return True
    except Exception:
        return False


def _out(text):
    return _write(sys.stdout, text)


def _err(text):
    return _write(sys.stderr, text)


def _log(text):
    """يُلحق نصّاً بملف السجلّ — القناة الوحيدة المضمونة في نسخة نافذية."""
    try:
        from . import config

        path = config.LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("[%s] %s\n" % (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text
            ))
        return path
    except Exception:
        return None


def _show_error_box(text):
    """نافذة خطأ عربية — تُرى حتى حين لا يوجد مجرى إخراج أصلاً.

    داخل ``try`` كذلك: إن كان الفشل في Qt نفسها فلا يجوز أن يُسقط عرضُ الخطأ
    البرنامجَ مرّة أخرى، ويبقى السجلّ هو الأثر.
    """
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("تعذّر تشغيل المنظومة")
        box.setText(text)
        box.exec()
        return True
    except Exception:
        return False


def _report_fatal(summary, detail="", show_dialog=True):
    """يوصل خطأ إقلاع قاتلاً إلى المستخدم مهما كانت صورة التشغيل.

    ``show_dialog=False`` في الأوضاع **غير التفاعلية** (`--backup-now` مهمّةً
    مجدولة، و`--self-test` في خادم البناء): `QMessageBox.exec()` تحجز الخيط
    حتى يضغط أحدٌ «موافق»، ولا أحد أمام الجهاز ليلاً. فتبقى العملية معلَّقة،
    وتتعطّل معها كل نسخة تالية — فيكتشف المكتب أن نسخه توقّفت منذ أسابيع يوم
    يحتاجها. والمجرى والسجلّ يبقيان عاملين في الحالتين، فلا يضيع الخبر.
    """
    full = summary if not detail else "%s\n\n%s" % (summary, detail)

    _err(full + "\n")
    log_path = _log(full)

    if not show_dialog:
        return

    message = summary
    if log_path is not None:
        message += "\n\nحُفظت التفاصيل في:\n%s" % log_path
    _show_error_box(message)


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

    # حالة الاشتراك تُفحص قبل أي شيء، فتُثبَّت مزايا النسخة على التطبيق كلّه
    from .services import subscription

    subscription.boot()

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

    from .services import subscription
    from .ui.activation_window import ActivationWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    rtl.apply(app)

    state = {"main_window": None, "activation": None}

    login = LoginWindow()

    def on_login(user):
        window = MainWindow(user)
        state["main_window"] = window
        login.close()
        window.show()

    login.logged_in.connect(on_login)

    # الاشتراك يُفحص قبل شاشة الدخول: لا معنى لتسجيل دخول إلى برنامج مقفل
    status = subscription.status()
    if status.is_usable and not self_test:
        login.show()
    elif not self_test:
        activation = ActivationWindow(status)
        state["activation"] = activation

        def on_activated(new_status):
            if new_status.is_usable:
                activation.close()
                login.show()

        activation.activated.connect(on_activated)
        activation.show()
    else:
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
        _report_fatal("فشل النسخ الاحتياطي: %s" % error, show_dialog=False)
        return 1

    _out("تمت النسخة الاحتياطية: %s\n" % result.get("file_name"))
    return 0


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        from . import config

        _out("%s — الإصدار %s\n" % (config.APP_TITLE_AR, config.APP_VERSION))
        return 0

    # الأوضاع غير التفاعلية لا يقف أمامها أحد ليغلق نافذة
    interactive = not (args.backup_now or args.self_test)

    try:
        _bootstrap(args.data_dir)
    except Exception as error:
        _report_fatal("تعذّرت تهيئة قاعدة البيانات:\n%s" % error,
                      traceback.format_exc(), show_dialog=interactive)
        return 1

    if args.backup_now:
        return run_backup()

    if args.self_test:
        # منصّة بلا شاشة: تسمح بفحص الواجهة في بيئات البناء والاختبار
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    return run_gui(self_test=args.self_test)


if __name__ == "__main__":
    sys.exit(main())

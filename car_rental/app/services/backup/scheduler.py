# -*- coding: utf-8 -*-
"""جدولة النسخ الاحتياطي اليومي وتشغيله في خيط منفصل.

**لماذا خيط منفصل؟** رفع ملف إلى الإنترنت عملية بطيئة وغير مضمونة المدّة.
تنفيذها في الخيط الرئيسي يُجمّد الواجهة تماماً فيظنّ المستخدم أن البرنامج
تعطّل. ولذلك يعمل النسخ في ``QThread`` ويُبلّغ الواجهة بالنتيجة عبر إشارة.

كل خيط يفتح اتصاله الخاص بقاعدة البيانات (انظر ``core/db.py``)، لأن كائن
اتصال SQLite لا يجوز تشاركه بين الخيوط.
"""

import datetime

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from ...core import db, session
from ...repositories import settings_repo
from . import backup_service

# فاصل الفحص الدوري: ساعة واحدة. التطبيق قد يبقى مفتوحاً أياماً في المكتب،
# فلا يكفي الفحص عند الإقلاع وحده.
CHECK_INTERVAL_MS = 60 * 60 * 1000


class BackupWorker(QObject):
    """عامل النسخ الاحتياطي: يعمل داخل ``QThread``."""

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, mode="manual", user=None):
        super().__init__()
        self._mode = mode
        self._user = user

    def run(self):
        # الجلسة مخزَّنة لكل خيط، فتُنقل إلى هذا الخيط ليُسجَّل منفّذ العملية
        if self._user is not None:
            session.login(self._user)

        try:
            result = backup_service.run_backup(mode=self._mode)
            self.finished.emit(result)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            db.close_connection()


class BackupScheduler(QObject):
    """يراقب موعد النسخة اليومية ويشغّلها عند حلوله.

    الاستخدام من النافذة الرئيسية:
        self.scheduler = BackupScheduler(self)
        self.scheduler.backup_finished.connect(...)
        self.scheduler.start()
    """

    backup_started = pyqtSignal(str)
    backup_finished = pyqtSignal(dict)
    backup_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.check_now)
        self._thread = None
        self._worker = None

    # -- التحكّم ------------------------------------------------------------
    def start(self, check_immediately=True):
        self._timer.start()
        if check_immediately:
            # تأخير بسيط حتى تظهر النافذة أولاً فلا يبدو الإقلاع بطيئاً
            QTimer.singleShot(4000, self.check_now)

    def stop(self):
        self._timer.stop()

    def is_running(self):
        return self._thread is not None and self._thread.isRunning()

    # -- المنطق -------------------------------------------------------------
    def due(self):
        """هل حان موعد النسخة اليومية؟"""
        if not settings_repo.get_bool("backup_enabled", True):
            return False
        if not settings_repo.get_bool("auto_backup_daily", True):
            return False

        last = settings_repo.get("last_backup_at", "")
        if not last:
            return True

        try:
            last_time = datetime.datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return True

        return last_time.date() < datetime.date.today()

    def check_now(self):
        """يفحص الموعد ويشغّل النسخة إن حان، دون أي إزعاج للمستخدم إن لم يحن."""
        from . import drive_client

        if self.is_running() or not self.due():
            return False
        if drive_client.status_message() is not None:
            return False  # الربط غير مكتمل: تُترك المحاولة بصمت

        return self.run_backup(mode="auto")

    def run_backup(self, mode="manual"):
        """يبدأ عملية نسخ في خيط منفصل. يُرجع False إن كانت هناك عملية جارية."""
        if self.is_running():
            return False

        self._thread = QThread(self)
        self._worker = BackupWorker(mode=mode, user=session.current_user())
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self.backup_started.emit(mode)
        self._thread.start()
        return True

    # -- الإنهاء ------------------------------------------------------------
    def _cleanup(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def _on_finished(self, result):
        self._cleanup()
        self.backup_finished.emit(result)

    def _on_failed(self, message):
        self._cleanup()
        self.backup_failed.emit(message)

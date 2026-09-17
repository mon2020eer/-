# -*- coding: utf-8 -*-
"""صفحة النسخ الاحتياطي على Google Drive — للمدير فقط.

تعرض حالة الربط، وتسمح بالنسخ اليدوي الفوري، وباستعادة أي نسخة سابقة،
وتُظهر سجلّ كل المحاولات ناجحها وفاشلها.
"""

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ... import config
from ...repositories import settings_repo
from ...services.backup import backup_service, drive_client
from ..widgets.common import (
    Card, DataTable, PageHeader, confirm, fix_dates, primary_button, show_error,
    show_info, show_warning,
)


def _human_size(size):
    try:
        size = float(size or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("بايت", "ك.ب", "م.ب", "ج.ب"):
        if size < 1024 or unit == "ج.ب":
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "—"


class RestoreDialog(QDialog):
    """حوار اختيار نسخة من Drive لاستعادتها."""

    def __init__(self, backups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("استعادة نسخة احتياطية")
        self.setMinimumSize(640, 420)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.selected_file_id = None

        layout = QVBoxLayout(self)

        warning = QLabel(
            "⚠ الاستعادة تستبدل قاعدة البيانات الحالية بالكامل.\n"
            "ستُحفظ نسخة أمان من البيانات الحالية تلقائياً قبل الاستبدال،\n"
            "ويجب إعادة تشغيل التطبيق بعد إتمام العملية."
        )
        warning.setWordWrap(True)
        warning.setObjectName("loginError")
        layout.addWidget(warning)

        self.table = DataTable(
            [("name", "اسم النسخة"), ("createdTime", "تاريخ الإنشاء"), ("size", "الحجم")],
            stretch_column=0,
        )
        # نسخ Drive لا تحمل عمود id، فتُجهَّز الصفوف يدوياً
        self.table.model_.removeRows(0, self.table.model_.rowCount())
        self._backups = list(backups)

        from PyQt6.QtGui import QStandardItem

        for item in self._backups:
            cells = [
                QStandardItem(item.get("name", "")),
                QStandardItem(str(item.get("createdTime", ""))[:19].replace("T", " ")),
                QStandardItem(_human_size(item.get("size"))),
            ]
            for cell in cells:
                cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells[0].setData(item.get("id"), Qt.ItemDataRole.UserRole)
            self.table.model_.appendRow(cells)

        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        restore = QPushButton("استعادة النسخة المختارة")
        restore.setObjectName("danger")
        restore.clicked.connect(self._accept)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(restore)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _accept(self):
        file_id = self.table.selected_id()
        if not file_id:
            show_error(self, "اختر نسخة أولاً.")
            return
        self.selected_file_id = file_id
        self.accept()


class BackupPage(QWidget):
    """شاشة إدارة النسخ الاحتياطي."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        self.header = PageHeader(
            "النسخ الاحتياطي", "حفظ نسخة يومية من قاعدة البيانات في Google Drive"
        )
        layout.addWidget(self.header)

        # --- حالة الربط ---
        status_card = Card()
        status_title = QLabel("حالة الربط")
        status_title.setObjectName("sectionTitle")

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        buttons = QHBoxLayout()
        self.link_button = primary_button("ربط حساب Google")
        self.link_button.clicked.connect(self._link)
        self.backup_button = QPushButton("نسخ احتياطي الآن")
        self.backup_button.clicked.connect(self._backup_now)
        self.local_button = QPushButton("نسخة محلية فقط")
        self.local_button.clicked.connect(self._local_snapshot)
        self.restore_button = QPushButton("استعادة نسخة")
        self.restore_button.setObjectName("danger")
        self.restore_button.clicked.connect(self._restore)
        self.unlink_button = QPushButton("فكّ الربط")
        self.unlink_button.clicked.connect(self._unlink)

        for button in (self.link_button, self.backup_button, self.local_button,
                       self.restore_button, self.unlink_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        status_card.body.addWidget(status_title)
        status_card.body.addWidget(self.status_label)
        status_card.body.addLayout(buttons)
        layout.addWidget(status_card)

        # --- سجلّ المحاولات ---
        log_card = Card()
        log_title = QLabel("سجلّ عمليات النسخ")
        log_title.setObjectName("sectionTitle")

        self.log_table = DataTable(
            [
                ("started_at", "وقت البدء"),
                ("mode", "النوع"),
                ("status", "النتيجة"),
                ("file_name", "الملف"),
                ("file_size", "الحجم"),
                ("triggered_by_name", "المنفّذ"),
                ("message", "الرسالة"),
            ],
            stretch_column=6,
        )
        log_card.body.addWidget(log_title)
        log_card.body.addWidget(self.log_table)
        layout.addWidget(log_card, 1)

    # ------------------------------------------------------------------
    def _format_log(self, row, key):
        labels = {"auto": "تلقائي", "manual": "يدوي", "restore": "استعادة",
                  "running": "جارية", "success": "نجحت", "failed": "فشلت"}
        if key in ("mode", "status"):
            return labels.get(row[key], row[key])
        if key == "file_size":
            return _human_size(row["file_size"])
        if key == "started_at":
            return str(row["started_at"])[:19]
        return (row[key] if key in row.keys() else "") or "—"

    def _scheduler(self):
        """يصل إلى مجدول النافذة الرئيسية ليعمل النسخ في خيط منفصل."""
        parent = self.parent()
        while parent is not None and not hasattr(parent, "scheduler"):
            parent = parent.parent()
        return getattr(parent, "scheduler", None)

    # ------------------------------------------------------------------
    def _link(self):
        try:
            email = drive_client.link_account()
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "تم ربط حساب Google بنجاح:\n%s" % (email or "—"))
        self.refresh()

    def _unlink(self):
        if not confirm(self, "فكّ الربط سيوقف النسخ التلقائي حتى تربط الحساب مجدداً. متابعة؟"):
            return
        try:
            drive_client.unlink()
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "تم فكّ الربط.")
        self.refresh()

    def _backup_now(self):
        scheduler = self._scheduler()
        if scheduler is None:
            show_error(self, "تعذّر الوصول إلى مجدول النسخ.")
            return
        if not scheduler.run_backup(mode="manual"):
            show_warning(self, "هناك عملية نسخ جارية بالفعل.")
            return
        show_info(self, "بدأت عملية النسخ في الخلفية. يمكنك متابعة العمل، وستظهر النتيجة في السجل.")

    def _local_snapshot(self):
        """نسخة محلية مضغوطة بلا إنترنت — مفيدة قبل أي عملية حسّاسة."""
        try:
            path = backup_service.create_local_snapshot()
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "حُفظت نسخة محلية في:\n%s" % path)

    def _restore(self):
        try:
            backups = backup_service.list_remote_backups()
        except Exception as error:
            show_error(self, error)
            return

        if not backups:
            show_warning(self, "لا توجد نسخ مرفوعة في Google Drive بعد.")
            return

        dialog = RestoreDialog(backups, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if not confirm(
            self,
            "سيتم استبدال قاعدة البيانات الحالية. هل أنت متأكّد تماماً؟",
            title="تأكيد الاستعادة",
        ):
            return

        try:
            result = backup_service.restore_from_drive(dialog.selected_file_id)
        except Exception as error:
            show_error(self, error)
            return

        show_info(
            self,
            "تمت الاستعادة بنجاح.\nنسخة الأمان من البيانات السابقة:\n%s\n\n"
            "أغلق التطبيق وأعد تشغيله الآن." % result["safety_copy"],
            title="اكتملت الاستعادة",
        )

    # ------------------------------------------------------------------
    def refresh(self):
        try:
            problem = drive_client.status_message()
            linked = problem is None

            last = backup_service.last_successful()
            last_text = "آخر نسخة ناجحة: %s" % (
                str(last["finished_at"])[:19] if last and last["finished_at"] else "لا توجد بعد"
            )

            retention = settings_repo.get_int("backup_retention", 30)
            auto = settings_repo.get_bool("auto_backup_daily", True)

            if linked:
                self.status_label.setText(fix_dates(
                    "✅ الربط مكتمل والنسخ جاهز.\n%s\n"
                    "النسخ التلقائي اليومي: %s  |  عدد النسخ المحفوظة: %d\n"
                    "مجلد Drive: %s  |  مجلد البيانات المحلي: %s"
                    % (last_text, "مفعّل" if auto else "معطَّل", retention,
                       config.DRIVE_FOLDER_NAME, config.DATA_DIR)
                ))
            else:
                self.status_label.setText(fix_dates("⚠ %s\n\n%s" % (problem, last_text)))

            self.backup_button.setEnabled(linked)
            self.restore_button.setEnabled(linked)
            self.unlink_button.setEnabled(drive_client.is_linked())
            self.link_button.setText(
                "إعادة ربط حساب Google" if drive_client.is_linked() else "ربط حساب Google"
            )

            self.header.set_subtitle(
                "اليوم %s — النسخ التلقائي يعمل عند إقلاع التطبيق وكل ساعة"
                % datetime.date.today().isoformat()
            )
            self.log_table.fill(backup_service.recent_logs(100), self._format_log)
        except Exception as error:
            show_error(self, error)

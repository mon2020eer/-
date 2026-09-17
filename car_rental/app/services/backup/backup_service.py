# -*- coding: utf-8 -*-
"""خدمة النسخ الاحتياطي والاستعادة.

**لماذا لا نَنسخ ملف قاعدة البيانات نسخاً عادياً؟** لأن نسخ ملف SQLite أثناء
عمل التطبيق قد يلتقط الملف في منتصف عملية كتابة، فتخرج نسخة تالفة، ولأن وضع
WAL يبقي جزءاً من البيانات في ملف ``-wal`` منفصل. لذلك تُستخدم واجهة
``sqlite3.Connection.backup()`` الرسمية التي تُنتج نسخة متّسقة وآمنة والتطبيق
يعمل.

سلسلة العمليات: نسخة متّسقة ← فحص سلامة ← ضغط gzip ← رفع إلى Drive ←
حذف الزائد عن حدّ الاستبقاء ← تسجيل النتيجة في ``backup_logs``.
"""

import datetime
import gzip
import pathlib
import shutil
import sqlite3

from ... import config
from ...core import audit, db, features, session
from ...repositories import settings_repo
from . import drive_client


class BackupError(Exception):
    """خطأ في عملية النسخ أو الاستعادة برسالة عربية."""


def _timestamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _start_log(mode, conn=None):
    cursor = db.execute(
        "INSERT INTO backup_logs (mode, status, triggered_by) VALUES (?, 'running', ?)",
        (mode, session.current_user_id()),
        conn=conn,
    )
    return cursor.lastrowid


def _finish_log(log_id, status, file_name=None, file_size=None,
                drive_file_id=None, message=None, conn=None):
    db.execute(
        """UPDATE backup_logs
              SET status = ?, finished_at = datetime('now', 'localtime'),
                  file_name = ?, file_size = ?, drive_file_id = ?, message = ?
            WHERE id = ?""",
        (status, file_name, file_size, drive_file_id, message, log_id),
        conn=conn,
    )


def copy_database(source_db, target_db):
    """ينسخ قاعدة بيانات نسخاً **متّسقاً** عبر واجهة ``sqlite3.backup``.

    لا يُنسخ ملفّ القاعدة نسخاً مباشراً: في وضع WAL يبقى جزء من العمل المُودَع
    في ملفّ ``-wal`` منفصل حتى يُدمَج، فنسخُ الملفّ وحده يُخرج قاعدةً ناقصةً
    آخر ما سُجِّل — وقد تُنسخ أثناء كتابة جارية فتخرج متناقضة أصلاً.
    """
    source_db, target_db = pathlib.Path(source_db), pathlib.Path(target_db)
    target_db.parent.mkdir(parents=True, exist_ok=True)

    source = db.connect(source_db)
    try:
        destination = db.connect(target_db)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target_db


def create_local_snapshot(target_path=None, source_db=None):
    """ينشئ نسخة متّسقة مضغوطة من قاعدة البيانات ويُرجع مسارها.

    تعمل بلا إنترنت ولا مكتبات Google، وهي أيضاً الأساس للنسخ اليدوي المحلي.
    """
    config.ensure_directories()
    source_db = pathlib.Path(source_db) if source_db else config.DB_PATH

    if target_path is None:
        target_path = config.BACKUP_DIR / ("carrental_%s.db.gz" % _timestamp())
    target_path = pathlib.Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    raw_path = target_path.with_suffix("")  # الملف غير المضغوط مؤقتاً
    if raw_path.exists():
        raw_path.unlink()

    source = db.connect(source_db)
    destination = db.connect(raw_path)
    try:
        source.backup(destination)          # نسخة متّسقة عبر واجهة SQLite الرسمية
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise BackupError("النسخة الناتجة تالفة (فحص السلامة: %s)." % integrity)
    finally:
        destination.close()
        source.close()

    with open(raw_path, "rb") as src, gzip.open(target_path, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    raw_path.unlink(missing_ok=True)

    return target_path


def verify_snapshot(archive_path):
    """يتحقّق من سلامة نسخة مضغوطة: يفكّها ويشغّل فحص سلامة SQLite عليها."""
    archive_path = pathlib.Path(archive_path)
    temp_db = archive_path.with_name(archive_path.stem + ".verify.db")
    cleanup_error = None

    try:
        with gzip.open(archive_path, "rb") as src, open(temp_db, "wb") as dst:
            shutil.copyfileobj(src, dst)

        conn = db.connect(temp_db)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
        finally:
            conn.close()
    except (OSError, EOFError, sqlite3.DatabaseError) as error:
        # ملف غير مضغوط صحيح، أو مضغوط لكنّه ليس قاعدة بيانات SQLite أصلاً
        raise BackupError("ملف النسخة تالف أو غير صالح: %s" % error)
    finally:
        # تنظيف ملف مؤقّت لا يجوز أن يطغى على سبب الفشل الحقيقي: لو تعذّر
        # حذفه — لأن مضاد فيروسات يفحصه مثلاً — فالمهمّ أن تصل رسالة التلف
        # إلى المستخدم، لا أن يحلّ محلّها خطأ نظام غامض.
        try:
            temp_db.unlink(missing_ok=True)
        except OSError as cleanup_failure:
            cleanup_error = cleanup_failure

    if result != "ok" or not tables:
        raise BackupError("ملف النسخة تالف ولا يصلح للاستعادة.")

    # أمّا إن كانت النسخة **سليمة** وتعذّر التنظيف، فالسكوت خطأ: يبقى ملفّ
    # قاعدة بيانات كامل غير مضغوط على القرص — بيانات عملاء المكتب مكشوفةً في
    # ملفّ لا يعرف أحد أنه وُلد ولا أنه بقي.
    if cleanup_error is not None:
        raise BackupError(
            "النسخة سليمة، لكن تعذّر حذف الملف المؤقّت:\n%s\n%s"
            % (temp_db, cleanup_error)
        )
    return True


@features.requires_feature("cloud_backup")
def run_backup(mode="manual", conn=None, keep_local=True):
    """ينفّذ دورة نسخ كاملة إلى Google Drive ويُرجع ملخّص النتيجة.

    يُشغَّل في خيط منفصل من الواجهة (انظر ``scheduler.py``) فلا تتجمّد الشاشة.
    """
    log_id = _start_log(mode, conn=conn)
    archive = None

    try:
        if not drive_client.libraries_available() or not drive_client.credentials_present():
            raise BackupError(drive_client.status_message())

        archive = create_local_snapshot()
        size = archive.stat().st_size

        service = drive_client._service(allow_interactive=False)
        folder_id = settings_repo.get("drive_folder_id", "", conn=conn) or None
        if not folder_id:
            folder_id = drive_client.ensure_folder(service)
            settings_repo.set_value("drive_folder_id", folder_id, conn=conn)

        uploaded = drive_client.upload_file(archive, folder_id, service=service)

        removed = apply_retention(folder_id=folder_id, service=service, conn=conn)

        settings_repo.set_value(
            "last_backup_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), conn=conn
        )
        _finish_log(
            log_id, "success", uploaded.get("name"), size, uploaded.get("id"),
            "تم الرفع بنجاح%s" % (" وحُذفت %d نسخة قديمة" % removed if removed else ""),
            conn=conn,
        )
        audit.log("backup", "backup", log_id, {"mode": mode, "file": uploaded.get("name")},
                  conn=conn)

        return {
            "status": "success",
            "file_name": uploaded.get("name"),
            "file_id": uploaded.get("id"),
            "size": size,
            "removed": removed,
            "local_path": str(archive) if keep_local else None,
        }

    except Exception as error:
        _finish_log(log_id, "failed", message=str(error), conn=conn)
        raise BackupError(str(error))

    finally:
        if archive and not keep_local:
            pathlib.Path(archive).unlink(missing_ok=True)


def apply_retention(folder_id=None, service=None, conn=None):
    """يحذف النسخ الزائدة عن حدّ الاستبقاء ويُرجع عدد المحذوف."""
    keep = settings_repo.get_int("backup_retention", 30, conn=conn)
    if keep <= 0:
        return 0

    files = drive_client.list_backups(folder_id=folder_id, limit=200, service=service)
    surplus = files[keep:]

    removed = 0
    for item in surplus:
        try:
            drive_client.delete_file(item["id"], service=service)
            removed += 1
        except drive_client.DriveError:
            # فشل حذف نسخة قديمة لا يُفشل النسخ الاحتياطي نفسه
            continue

    return removed


def list_remote_backups():
    """يسرد النسخ المتاحة في Drive مع أحجامها وتواريخها."""
    if not drive_client.libraries_available() or not drive_client.credentials_present():
        raise BackupError(drive_client.status_message())
    return drive_client.list_backups()


def restore_from_drive(file_id, conn=None):
    """يستعيد قاعدة البيانات من نسخة في Drive.

    خطوات الأمان بالترتيب:
        1. تنزيل النسخة إلى ملف مؤقّت.
        2. فحص سلامتها قبل المساس بأي شيء.
        3. حفظ نسخة أمان من القاعدة الحالية (``.pre-restore``).
        4. إغلاق الاتصالات ثم الاستبدال.

    يجب إعادة تشغيل التطبيق بعد الاستعادة.
    """
    session.require_login()
    log_id = _start_log("restore", conn=conn)

    try:
        config.ensure_directories()
        downloaded = config.BACKUP_DIR / ("restore_%s.db.gz" % _timestamp())
        drive_client.download_file(file_id, downloaded)

        verify_snapshot(downloaded)

        restored_db = downloaded.with_suffix("")
        with gzip.open(downloaded, "rb") as src, open(restored_db, "wb") as dst:
            shutil.copyfileobj(src, dst)

        safety_copy = config.DB_PATH.with_name(
            config.DB_PATH.name + ".pre-restore-%s" % _timestamp()
        )
        if config.DB_PATH.is_file():
            # آخر خطّ رجعة لصاحب المكتب إن استعاد نسخةً خطأً، فلا تُؤخذ بنسخ
            # الملفّ: ما في ملفّ `-wal` لم يُدمَج بعد وكان يضيع من النسخة.
            copy_database(config.DB_PATH, safety_copy)

        _finish_log(log_id, "success", downloaded.name,
                    downloaded.stat().st_size, file_id,
                    "تم التنزيل والتحقّق؛ بانتظار إعادة التشغيل", conn=conn)
        audit.log("restore", "backup", log_id, {"file_id": file_id}, conn=conn)

        # إغلاق الاتصال قبل استبدال الملف، وحذف ملفات WAL المصاحبة
        db.close_connection()
        for suffix in ("-wal", "-shm"):
            pathlib.Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
        shutil.move(str(restored_db), str(config.DB_PATH))
        downloaded.unlink(missing_ok=True)

        return {"status": "success", "safety_copy": str(safety_copy)}

    except Exception as error:
        _finish_log(log_id, "failed", message=str(error), conn=conn)
        raise BackupError(str(error))


def recent_logs(limit=50, conn=None):
    return db.query(
        """SELECT b.*, u.full_name AS triggered_by_name
             FROM backup_logs b LEFT JOIN users u ON u.id = b.triggered_by
            ORDER BY b.id DESC LIMIT ?""",
        (limit,),
        conn=conn,
    )


def last_successful(conn=None):
    return db.query_one(
        "SELECT * FROM backup_logs WHERE status = 'success' AND mode != 'restore' "
        "ORDER BY id DESC LIMIT 1",
        conn=conn,
    )

# -*- coding: utf-8 -*-
"""اختبارات النسخ الاحتياطي والاستعادة بعميل Drive وهمي.

الاختبارات لا تلمس الإنترنت ولا حساب Google إطلاقاً: يُستبدل عميل Drive
بعميل وهمي يحاكي الرفع والسرد والتنزيل داخل مجلد محلي، فنختبر **منطقنا** لا
منطق Google.
"""

import gzip
import pathlib
import shutil

import pytest

from app import config
from app.core import db
from app.services.backup import backup_service, drive_client


# ---------------------------------------------------------------------------
# عميل Drive وهمي
# ---------------------------------------------------------------------------
class FakeDrive(object):
    """يحاكي واجهة ``drive_client`` بمجلد محلي بدل السحابة."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = {}
        self.counter = 0

    def upload(self, local_path, folder_id=None, remote_name=None, service=None):
        self.counter += 1
        file_id = "file-%d" % self.counter
        name = remote_name or pathlib.Path(local_path).name
        target = self.root / ("%s_%s" % (file_id, name))
        shutil.copy2(str(local_path), str(target))

        record = {
            "id": file_id,
            "name": name,
            "size": target.stat().st_size,
            "createdTime": "2026-09-14T10:0%d:00Z" % self.counter,
            "_path": str(target),
        }
        self.files[file_id] = record
        return record

    def list(self, folder_id=None, limit=100, service=None):
        return sorted(self.files.values(), key=lambda item: item["id"], reverse=True)[:limit]

    def download(self, file_id, target_path, service=None):
        source = self.files[file_id]["_path"]
        target_path = pathlib.Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, str(target_path))
        return target_path

    def delete(self, file_id, service=None):
        record = self.files.pop(file_id, None)
        if record:
            pathlib.Path(record["_path"]).unlink(missing_ok=True)
        return True


@pytest.fixture()
def fake_drive(conn, admin, tmp_path, monkeypatch):
    """يركّب العميل الوهمي مكان عميل Drive الحقيقي."""
    drive = FakeDrive(tmp_path / "fake_drive")

    monkeypatch.setattr(drive_client, "libraries_available", lambda: True)
    monkeypatch.setattr(drive_client, "credentials_present", lambda: True)
    monkeypatch.setattr(drive_client, "is_linked", lambda: True)
    monkeypatch.setattr(drive_client, "status_message", lambda: None)
    monkeypatch.setattr(drive_client, "_service", lambda allow_interactive=True: None)
    monkeypatch.setattr(drive_client, "ensure_folder",
                        lambda service=None, folder_name=None: "folder-1")
    monkeypatch.setattr(drive_client, "upload_file", drive.upload)
    monkeypatch.setattr(drive_client, "list_backups", drive.list)
    monkeypatch.setattr(drive_client, "download_file", drive.download)
    monkeypatch.setattr(drive_client, "delete_file", drive.delete)

    return drive


# ---------------------------------------------------------------------------
# النسخة المحلية
# ---------------------------------------------------------------------------
def test_local_snapshot_is_valid_gzip_database(conn, admin, sample_vehicle):
    archive = backup_service.create_local_snapshot()

    assert archive.exists()
    assert archive.suffixes[-1] == ".gz"
    backup_service.verify_snapshot(archive)     # يرفع استثناءً إن كانت تالفة


def test_snapshot_contains_the_actual_data(conn, admin, sample_vehicle, tmp_path):
    """النسخة يجب أن تحمل البيانات فعلاً، لا ملفاً فارغاً بحجم صحيح."""
    archive = backup_service.create_local_snapshot()

    restored = tmp_path / "check.db"
    with gzip.open(archive, "rb") as src, open(restored, "wb") as dst:
        shutil.copyfileobj(src, dst)

    copy = db.connect(restored)
    try:
        plates = [row[0] for row in copy.execute("SELECT plate_number FROM vehicles")]
    finally:
        copy.close()

    assert "5-12345" in plates


def test_corrupt_archive_is_detected(conn, admin, tmp_path):
    bad = tmp_path / "corrupt.db.gz"
    with gzip.open(bad, "wb") as handle:
        handle.write("ليست قاعدة بيانات إطلاقاً".encode("utf-8"))

    with pytest.raises(backup_service.BackupError):
        backup_service.verify_snapshot(bad)


# ---------------------------------------------------------------------------
# دورة النسخ الكاملة
# ---------------------------------------------------------------------------
def test_backup_cycle_uploads_and_logs(conn, admin, sample_vehicle, fake_drive):
    result = backup_service.run_backup(mode="manual")

    assert result["status"] == "success"
    assert len(fake_drive.files) == 1

    log = backup_service.last_successful(conn=conn)
    assert log["status"] == "success"
    assert log["drive_file_id"] == result["file_id"]


def test_failed_backup_is_logged(conn, admin, monkeypatch):
    monkeypatch.setattr(drive_client, "libraries_available", lambda: False)
    monkeypatch.setattr(drive_client, "status_message", lambda: "المكتبات غير مثبَّتة")

    with pytest.raises(backup_service.BackupError):
        backup_service.run_backup(mode="manual")

    logs = backup_service.recent_logs(conn=conn)
    assert logs[0]["status"] == "failed"
    assert "المكتبات" in logs[0]["message"]


def test_retention_removes_surplus_backups(conn, admin, fake_drive):
    from app.repositories import settings_repo

    settings_repo.set_value("backup_retention", "2", conn=conn)

    for _ in range(4):
        settings_repo.set_value("last_backup_at", "", conn=conn)
        backup_service.run_backup(mode="manual")

    assert len(fake_drive.files) == 2


def test_restore_replaces_database_and_keeps_safety_copy(
    conn, admin, sample_customer, sample_vehicle, fake_drive
):
    from app.repositories import customers_repo

    # 1) نسخة تحتوي عميلاً واحداً
    result = backup_service.run_backup(mode="manual")

    # 2) إضافة عميل ثانٍ بعد النسخة
    customers_repo.create(
        {
            "full_name": "سالم الفيتوري", "phone": "0911111111",
            "national_id": "22222222", "license_number": "LC-99",
        },
        conn=conn,
    )
    assert len(customers_repo.search()) == 2

    # 3) الاستعادة تُعيد الحالة إلى عميل واحد
    restore = backup_service.restore_from_drive(result["file_id"], conn=conn)

    assert pathlib.Path(restore["safety_copy"]).is_file()
    assert len(customers_repo.search()) == 1


def test_restore_refuses_corrupt_backup(conn, admin, fake_drive, tmp_path):
    bad = tmp_path / "bad.db.gz"
    with gzip.open(bad, "wb") as handle:
        handle.write(b"tampered")
    record = fake_drive.upload(bad)

    with pytest.raises(backup_service.BackupError):
        backup_service.restore_from_drive(record["id"], conn=conn)

    # قاعدة البيانات الأصلية سليمة ولم تُمس
    assert config.DB_PATH.is_file()


# ---------------------------------------------------------------------------
# تسريب مِقبض الملف عند فتح اتصال على ملف ليس قاعدة بيانات
# ---------------------------------------------------------------------------
def test_failed_connect_closes_the_handle(app_home, tmp_path, monkeypatch):
    """اتصال فشل ضبطُه يجب أن يُغلق، وإلّا بقي مِقبض الملف مفتوحاً.

    ``sqlite3.connect`` ينجح على أي ملف ولا يقرأ محتواه؛ ولا يظهر أنه ليس
    قاعدة بيانات إلّا عند أول استعلام — بعد أن صار الاتصال قائماً. وتركُه
    مفتوحاً يمنع حذف الملف على ويندوز، فيحلّ خطأ النظام محلّ رسالة التطبيق.

    يُفحص هنا بمراقبة الاتصال نفسه لا بمحاولة الحذف: الحذف ينجح على لينكس ولو
    بقي المِقبض مفتوحاً، فلا يكشف العطب — وهذا ما جعله يمرّ حتى ظهر على ويندوز.
    """
    import sqlite3

    from app.core import db

    opened = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)

    garbage = tmp_path / "ليست-قاعدة.db"
    garbage.write_bytes(b"\x00\x01 not a database at all")

    with pytest.raises(sqlite3.DatabaseError):
        db.connect(garbage)

    assert opened, "لم يُفتح اتصال أصلاً — تغيّر مسار التنفيذ"
    with pytest.raises(sqlite3.ProgrammingError):
        opened[-1].execute("SELECT 1")          # مغلق فعلاً


def test_verify_snapshot_leaves_no_temp_file_behind(conn, admin, tmp_path):
    """النسخة التالفة تُرفض **ولا تترك أثراً** في مجلد النسخ.

    الملف المؤقّت `.verify.db` كان يبقى على ويندوز لأن مِقبضه لم يُغلق،
    فتتراكم ملفات لا يعرف صاحب المكتب ما هي ولا يجرؤ على حذفها.
    """
    bad = tmp_path / "corrupt.db.gz"
    with gzip.open(bad, "wb") as handle:
        handle.write("ليست قاعدة بيانات إطلاقاً".encode("utf-8"))

    with pytest.raises(backup_service.BackupError) as error:
        backup_service.verify_snapshot(bad)

    # الرسالة رسالة التطبيق، لا خطأ نظام مسرَّب
    assert "ملف النسخة تالف" in str(error.value)

    leftovers = [path.name for path in tmp_path.glob("*.verify.db")]
    assert leftovers == [], "بقيت ملفات مؤقّتة: %s" % leftovers

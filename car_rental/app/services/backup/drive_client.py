# -*- coding: utf-8 -*-
"""عميل Google Drive: المصادقة ورفع الملفات وسردها وتنزيلها.

**نطاق الصلاحية المطلوب واحد فقط:** ``drive.file`` — وهو يمنح التطبيق حقّ
الوصول إلى **الملفات التي أنشأها هو فقط**، لا إلى بقيّة محتوى حساب Drive.
هذا أقلّ امتياز ممكن يؤدّي الغرض، ولا يجوز توسيعه إلى ``drive`` الكامل.

المكتبات مستوردة **داخل الدوال** لا في رأس الملف، لسببين:
    • التطبيق يجب أن يعمل كاملاً بلا مكتبات Google إن لم يُثبّتها المستخدم.
    • تقصير زمن إقلاع التطبيق.
"""

import io
import pathlib

from ... import config


class DriveError(Exception):
    """خطأ في التعامل مع Google Drive برسالة عربية جاهزة للعرض."""


def libraries_available():
    """هل مكتبات Google مثبَّتة؟"""
    try:
        import google.oauth2.credentials  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
    except Exception:
        # لا يُكتفى بـ ImportError: تثبيت مكسور لمكتبة cryptography مثلاً يرفع
        # استثناءً من نوع آخر، ويجب ألّا يُسقط التطبيق كلّه بسبب ميزة اختيارية.
        return False
    return True


def credentials_present():
    """هل وضع المالك ملف ``credentials.json`` في مجلد البيانات؟"""
    return config.GOOGLE_CREDENTIALS_PATH.is_file()


def is_linked():
    """هل سبق ربط الحساب (يوجد رمز مميّز محفوظ)؟"""
    return config.GOOGLE_TOKEN_PATH.is_file()


def status_message():
    """رسالة عربية تصف جاهزية النسخ الاحتياطي، أو None إن كان كل شيء جاهزاً."""
    if not libraries_available():
        return (
            "مكتبات Google غير مثبَّتة. شغّل الأمر:\n"
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )
    if not credentials_present():
        return (
            "ملف بيانات الاعتماد credentials.json غير موجود.\n"
            "راجع دليل «إعداد Google Drive» ثم ضع الملف في:\n%s"
            % config.DATA_DIR
        )
    if not is_linked():
        return "لم يُربط حساب Google بعد. اضغط «ربط حساب Google» لإتمام الربط."
    return None


def unlink():
    """يحذف الرمز المميّز المحفوظ، فيلزم ربط الحساب من جديد."""
    try:
        config.GOOGLE_TOKEN_PATH.unlink(missing_ok=True)
    except OSError as error:
        raise DriveError("تعذّر حذف رمز الربط: %s" % error)
    return True


def _load_credentials(allow_interactive=True):
    """يحمّل بيانات الاعتماد، ويجدّدها أو يطلب ربطاً جديداً عند الحاجة."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if config.GOOGLE_TOKEN_PATH.is_file():
        try:
            creds = Credentials.from_authorized_user_file(
                str(config.GOOGLE_TOKEN_PATH), config.DRIVE_SCOPES
            )
        except ValueError:
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds
        except Exception:
            creds = None  # الرمز المميّز لم يعد صالحاً: نطلب ربطاً جديداً

    if not allow_interactive:
        raise DriveError("انتهت صلاحية ربط حساب Google. أعد الربط من شاشة النسخ الاحتياطي.")

    if not credentials_present():
        raise DriveError(status_message())

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.GOOGLE_CREDENTIALS_PATH), config.DRIVE_SCOPES
    )
    # يفتح المتصفّح ويستقبل الاستجابة على منفذ محلي مؤقّت
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_credentials(creds)
    return creds


def _save_credentials(creds):
    config.ensure_directories()
    config.GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    # تقييد أذونات الملف على لينكس/ماك؛ في ويندوز تحكمه أذونات مجلد المستخدم
    try:
        config.GOOGLE_TOKEN_PATH.chmod(0o600)
    except OSError:
        pass


def _service(allow_interactive=True):
    from googleapiclient.discovery import build

    creds = _load_credentials(allow_interactive=allow_interactive)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def link_account():
    """يبدأ تدفّق الربط التفاعلي ويُرجع بريد الحساب المرتبط."""
    if not libraries_available():
        raise DriveError(status_message())

    service = _service(allow_interactive=True)
    about = service.about().get(fields="user(emailAddress,displayName)").execute()
    return about.get("user", {}).get("emailAddress", "")


def ensure_folder(service=None, folder_name=None):
    """يجد مجلد النسخ الاحتياطي في Drive أو ينشئه، ويُرجع معرّفه."""
    from googleapiclient.errors import HttpError

    service = service or _service()
    folder_name = folder_name or config.DRIVE_FOLDER_NAME

    try:
        response = service.files().list(
            q=("mimeType = 'application/vnd.google-apps.folder' and trashed = false "
               "and name = '%s'" % folder_name.replace("'", "\\'")),
            spaces="drive",
            fields="files(id, name)",
            pageSize=10,
        ).execute()

        files = response.get("files", [])
        if files:
            return files[0]["id"]

        folder = service.files().create(
            body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"},
            fields="id",
        ).execute()
        return folder["id"]

    except HttpError as error:
        raise DriveError("تعذّر تجهيز مجلد النسخ في Google Drive: %s" % error)


def upload_file(local_path, folder_id=None, remote_name=None, service=None):
    """يرفع ملفاً إلى مجلد النسخ ويُرجع بياناته."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    service = service or _service()
    folder_id = folder_id or ensure_folder(service)
    local_path = pathlib.Path(local_path)

    if not local_path.is_file():
        raise DriveError("ملف النسخة غير موجود: %s" % local_path)

    try:
        media = MediaFileUpload(str(local_path), mimetype="application/gzip", resumable=True)
        uploaded = service.files().create(
            body={"name": remote_name or local_path.name, "parents": [folder_id]},
            media_body=media,
            fields="id, name, size, createdTime",
        ).execute()
    except HttpError as error:
        raise DriveError("فشل رفع النسخة الاحتياطية: %s" % error)

    return uploaded


def list_backups(folder_id=None, limit=100, service=None):
    """يسرد النسخ المرفوعة، الأحدث أولاً."""
    from googleapiclient.errors import HttpError

    service = service or _service()
    folder_id = folder_id or ensure_folder(service)

    # تُتابَع الصفحات حتى يكتمل العدد المطلوب: الاكتفاء بالصفحة الأولى كان
    # يجعل سياسة الاستبقاء ترى بعض النسخ لا كلّها، فتُبقي عشرات ما ظنّت أنها
    # حذفتها ويمتلئ مجلد Drive بلا أن يفهم صاحب المكتب السبب.
    found, page_token = [], None
    try:
        while len(found) < limit:
            response = service.files().list(
                q="'%s' in parents and trashed = false" % folder_id,
                spaces="drive",
                fields="nextPageToken, files(id, name, size, createdTime)",
                orderBy="createdTime desc",
                pageSize=min(limit - len(found), 1000),
                pageToken=page_token,
            ).execute()

            page = response.get("files", [])
            found.extend(page)

            page_token = response.get("nextPageToken")
            if not page_token or not page:
                break
    except HttpError as error:
        raise DriveError("تعذّر سرد النسخ الاحتياطية: %s" % error)

    return found[:limit]


def download_file(file_id, target_path, service=None):
    """ينزّل نسخة من Drive إلى مسار محلي."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload

    service = service or _service()
    target_path = pathlib.Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    request = service.files().get_media(fileId=file_id)
    buffer = io.FileIO(str(target_path), "wb")
    try:
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as error:
        raise DriveError("فشل تنزيل النسخة: %s" % error)
    finally:
        # الإغلاق على كل طريق: تركُه على مسار الفشل يُسرّب مِقبضاً مع كل
        # محاولة، ويُبقي الملف مقفلاً على ويندوز فلا يُحذف ولا يُكتب عليه —
        # ومحاولات الاستعادة تتكرّر عادةً.
        buffer.close()

    return target_path


def delete_file(file_id, service=None):
    from googleapiclient.errors import HttpError

    service = service or _service()
    try:
        service.files().delete(fileId=file_id).execute()
    except HttpError as error:
        raise DriveError("تعذّر حذف نسخة قديمة: %s" % error)
    return True

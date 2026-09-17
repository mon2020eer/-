# -*- coding: utf-8 -*-
"""حراسة نقطة الدخول: ما ينكسر في النسخة المحزومة وحدها.

عطبان وصلا إلى جهاز المالك بعد بناء ناجح، وكلاهما **لا يظهر** عند
``python -m app`` ولا في أي اختبار قائم:

1. PyInstaller تشغّل ملفَ نقطة الدخول بلا سياق حزمة، فتسقط الاستيرادات النسبية.
2. النسخة النافذية تجعل ``sys.stdout`` و``sys.stderr`` قيمتهما ``None``،
   فينهار معالج الخطأ نفسه ويُخفي السبب الحقيقي.

ويُعاد إنتاج الأول هنا **بلا PyInstaller ولا ويندوز**: تشغيل ملف مباشرةً
(``python file.py``) يمنحه ``__package__ = None`` بالضبط كما تفعل PyInstaller.
"""

import os
import pathlib
import subprocess
import sys

import pytest

PROJECT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = PROJECT / "run.py"
PACKAGE_MAIN = PROJECT / "app" / "__main__.py"


def _run(script, tmp_path, *args):
    """يشغّل ملفاً مباشرةً كما تفعل PyInstaller: بلا ``-m`` وبلا سياق حزمة."""
    env = dict(os.environ)
    env["CAR_RENTAL_HOME"] = str(tmp_path)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONPATH", None)

    return subprocess.run(
        [sys.executable, str(script)] + list(args),
        capture_output=True, text=True, env=env, timeout=120,
        cwd=str(tmp_path),          # من مجلد آخر: لا يُعتمد على مجلد العمل
    )


# ---------------------------------------------------------------------------
# سياق الحزمة
# ---------------------------------------------------------------------------
def test_launcher_runs_as_a_plain_script(tmp_path):
    """`run.py` يعمل مشغَّلاً مباشرةً — وهي صورة تشغيل النسخة المحزومة."""
    result = _run(LAUNCHER, tmp_path, "--version")

    assert result.returncode == 0, result.stderr
    assert "الإصدار" in result.stdout
    assert "ImportError" not in result.stderr


def test_package_main_cannot_be_the_entry_point(tmp_path):
    """إثباتٌ أن الاختبار أعلاه يقيس العطب نفسه لا شيئاً مجاوراً له.

    `app/__main__.py` مشغَّلاً مباشرةً **يجب** أن يسقط بالخطأ الذي ظهر على
    جهاز المالك. فإن نجح يوماً فقد تغيّر شيء جوهري، والحارس الأول صار بلا معنى.
    """
    result = _run(PACKAGE_MAIN, tmp_path, "--version")

    assert result.returncode != 0
    assert "attempted relative import" in result.stderr


def test_package_still_runs_with_dash_m(tmp_path):
    """الطريق المعتاد للمطوّر لم يُكسر بالإصلاح."""
    env = dict(os.environ)
    env["CAR_RENTAL_HOME"] = str(tmp_path)
    env["QT_QPA_PLATFORM"] = "offscreen"

    result = subprocess.run(
        [sys.executable, "-m", "app", "--version"],
        capture_output=True, text=True, env=env, timeout=120, cwd=str(PROJECT),
    )
    assert result.returncode == 0, result.stderr
    assert "الإصدار" in result.stdout


# ---------------------------------------------------------------------------
# المخارج الغائبة في النسخة النافذية
# ---------------------------------------------------------------------------
def test_startup_failure_survives_missing_streams(app_home, monkeypatch, capsys):
    """فشل الإقلاع يجب أن يُرجع رمز خطأ لا أن يرفع استثناءً.

    هذا هو العطب الذي أخفى سببه: `sys.stderr.write` على `None` يُسقط معالج
    الخطأ نفسه، فيرى صاحب المكتب «'NoneType' object has no attribute 'write'»
    مهما كان الخلل الحقيقي.
    """
    from app import __main__ as entry

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    def explode(*args, **kwargs):
        raise RuntimeError("قاعدة البيانات مقفلة")

    monkeypatch.setattr(entry, "_bootstrap", explode)
    monkeypatch.setattr(entry, "_show_error_box", lambda text: True)

    assert entry.main([]) == 1          # لا استثناء


def test_startup_failure_is_written_to_the_log(app_home, monkeypatch):
    """السجلّ هو القناة المضمونة حين لا يوجد مجرى ولا شاشة."""
    from app import config
    from app import __main__ as entry

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(entry, "_show_error_box", lambda text: True)

    def explode(*args, **kwargs):
        raise RuntimeError("سبب الفشل الحقيقي")

    monkeypatch.setattr(entry, "_bootstrap", explode)
    entry.main([])

    assert config.LOG_PATH.is_file(), "لم يُكتب شيء في السجلّ"
    assert "سبب الفشل الحقيقي" in config.LOG_PATH.read_text(encoding="utf-8")


def test_write_helpers_tolerate_missing_streams(monkeypatch):
    from app import __main__ as entry

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    assert entry._out("نصّ") is False    # لم يُكتب، ولم يُرفع استثناء
    assert entry._err("نصّ") is False


def test_write_helpers_survive_a_broken_stream(monkeypatch):
    """مجرى مغلق أو معطوب لا يُسقط البرنامج كذلك."""
    from app import __main__ as entry

    class Broken(object):
        def write(self, text):
            raise ValueError("مجرى مغلق")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", Broken())
    assert entry._out("نصّ") is False


# ---------------------------------------------------------------------------
# المهمّة المجدولة لا تنتظر إنساناً
# ---------------------------------------------------------------------------
def test_scheduled_backup_failure_does_not_open_a_modal_dialog(app_home, monkeypatch):
    """`--backup-now` مهمّة مجدولة: نافذةٌ فيها تنتظر نقرةً لا تأتي.

    `QMessageBox.exec()` تحجز الخيط حتى يضغط أحدٌ «موافق»، ولا أحد أمام
    الجهاز ليلاً. فتبقى العملية معلَّقة، **وتتعطّل معها كل نسخة تالية** —
    فيكتشف المكتب أن نسخه توقّفت منذ أسابيع يوم يحتاجها.
    """
    from app import __main__ as entry

    shown = []
    monkeypatch.setattr(entry, "_show_error_box", lambda text: shown.append(text))

    def explode(*args, **kwargs):
        raise RuntimeError("قاعدة البيانات مقفلة")

    monkeypatch.setattr(entry, "_bootstrap", explode)

    assert entry.main(["--backup-now"]) == 1
    assert shown == [], "فُتحت نافذة في وضع غير تفاعلي"


def test_scheduled_backup_failure_still_reaches_the_log(app_home, monkeypatch):
    """ويبقى السبب مكتوباً: المنعُ للنافذة وحدها لا للتبليغ."""
    from app import config
    from app import __main__ as entry

    def failing_backup(*args, **kwargs):
        raise RuntimeError("انقطع الاتصال بـ Drive")

    from app.services.backup import backup_service

    monkeypatch.setattr(backup_service, "run_backup", failing_backup)
    monkeypatch.setattr(entry, "_show_error_box",
                        lambda text: pytest.fail("فُتحت نافذة في وضع غير تفاعلي"))

    assert entry.main(["--backup-now"]) == 1
    assert "انقطع الاتصال بـ Drive" in config.LOG_PATH.read_text(encoding="utf-8")


def test_self_test_does_not_open_a_modal_dialog(app_home, monkeypatch):
    """و`--self-test` كذلك: يعمل في خوادم البناء بلا إنسان أمامها."""
    from app import __main__ as entry

    monkeypatch.setattr(entry, "_show_error_box",
                        lambda text: pytest.fail("فُتحت نافذة في وضع غير تفاعلي"))

    def explode(*args, **kwargs):
        raise RuntimeError("قاعدة البيانات مقفلة")

    monkeypatch.setattr(entry, "_bootstrap", explode)
    assert entry.main(["--self-test"]) == 1


def test_interactive_startup_still_shows_the_dialog(app_home, monkeypatch):
    """أمّا التشغيل العادي فالنافذة فيه هي القناة الوحيدة: لا مجرى ولا سجلّ يُقرأ."""
    from app import __main__ as entry

    shown = []
    monkeypatch.setattr(entry, "_show_error_box", lambda text: shown.append(text))

    def explode(*args, **kwargs):
        raise RuntimeError("قاعدة البيانات مقفلة")

    monkeypatch.setattr(entry, "_bootstrap", explode)

    assert entry.main([]) == 1
    assert shown, "لم تظهر نافذة الخطأ في التشغيل التفاعلي"

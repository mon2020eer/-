# -*- coding: utf-8 -*-
"""حراسة سكربتات البناء.

هذه اختبارات تقرأ نصّاً لا تشغّل شيفرة، وقد لا تبدو اختبارات «حقيقية». لكن
أعطاب البناء الثلاثة التي وصلت إلى جهاز المالك كانت كلّها من هذا النوع: ترميز
ملف، وتثبيت حزمة متعفّن، ونداءُ أمر باسمه المجرَّد. ولا تكشفها اختبارات المنطق
ولا البناء الآلي — لأن مُشغّلات GitHub تختلف عن جهاز مكتب في ليبيا — فتكشفها
هذه في ثانية بدل دورة ذهاب وإياب كاملة.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "build" / "build_exe.ps1"
INSTALLER = ROOT / "build" / "installer.iss"
WORKFLOW = ROOT.parent / ".github" / "workflows" / "car-rental.yml"

# أدوات بايثون التي يضعها pip في مجلد Scripts. وجود ذلك المجلد في PATH ليس
# مضموناً على أجهزة المستخدمين، فتُنادى بـ ``python -m`` دائماً.
CONSOLE_SCRIPTS = ("pyinstaller", "pytest", "pip")

_BARE_CALL = re.compile(
    r"^[ \t]*(?:run:[ \t]*)?(%s)\b" % "|".join(CONSOLE_SCRIPTS),
    re.IGNORECASE,
)


def _command_lines(path, comment_prefix):
    """أسطر الأوامر وحدها: بلا تعليقات ولا أسطر فارغة."""
    text = path.read_bytes().decode("utf-8-sig")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(comment_prefix):
            continue
        yield number, line


@pytest.mark.parametrize(
    "path, comment_prefix",
    [(BUILD_SCRIPT, "#"), (WORKFLOW, "#")],
    ids=["build_exe.ps1", "workflow"],
)
def test_python_tools_are_called_through_the_interpreter(path, comment_prefix):
    """لا يُنادى ملف تنفيذي باسمه المجرَّد في سكربت بناء.

    `pyinstaller …` يسقط بـ «The term 'pyinstaller' is not recognized» على كل
    جهاز لا يضع مجلد Scripts في PATH — وقد وقع ذلك فعلاً عند المالك. أمّا
    `python -m PyInstaller` فيستعمل المفسّر نفسه الذي ثُبّتت فيه الحزمة.
    """
    if not path.exists():
        pytest.skip("الملف غير موجود في هذا السياق: %s" % path)

    offenders = [
        "%s:%d: %s" % (path.name, number, line.strip())
        for number, line in _command_lines(path, comment_prefix)
        if _BARE_CALL.match(line)
    ]

    assert not offenders, (
        "نداءات بأسماء مجرَّدة — استعمل python -m بدلها:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", [BUILD_SCRIPT, INSTALLER],
                         ids=["build_exe.ps1", "installer.iss"])
def test_windows_files_keep_their_utf8_bom(path):
    """بلا علامة BOM يقرأ PowerShell العربي الملفَّ بترميز CP1256.

    فتتحوّل الشدّة والشرطة الطويلة إلى علامات اقتباس ذكية، فينهار تحليل الملف
    برسالة «Missing closing '}'» التي لا تدلّ على السبب إطلاقاً.
    """
    assert path.exists(), path
    assert path.read_bytes()[:3] == b"\xef\xbb\xbf", (
        "فُقدت علامة BOM من %s — أعد حفظه UTF-8 with BOM" % path.name
    )


def test_pyinstaller_is_not_pinned_to_one_version():
    """تثبيت على رقم واحد يتعفّن مع أول بايثون أحدث فيُرفض عند التثبيت."""
    text = BUILD_SCRIPT.read_bytes().decode("utf-8-sig")
    assert "pyinstaller==" not in text.lower(), (
        "PyInstaller مثبَّت على رقم واحد — استعمل مدى مثل >=6.15,<7"
    )


def test_every_pip_call_is_checked_for_failure():
    """PowerShell لا يتوقّف عند فشل أمر خارجي، فيجب فحص رمز خروجه صراحةً.

    بدون ذلك يمضي السكربت بعد فشل التثبيت ويتّهم الاختبارات بفشل لم يقع.
    """
    text = BUILD_SCRIPT.read_bytes().decode("utf-8-sig")
    lines = text.splitlines()

    unchecked = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "pip install" not in stripped:
            continue
        if stripped.startswith("Write-Host"):
            continue          # نصّ رسالة للمستخدم لا أمر يُنفَّذ

        window = "\n".join(lines[max(0, index - 2):index + 1])
        if "Invoke-Step" not in window:
            unchecked.append("%d: %s" % (index + 1, stripped))

    assert not unchecked, (
        "نداءات pip غير مفحوصة الفشل — لُفّها بـ Invoke-Step:\n  "
        + "\n  ".join(unchecked)
    )

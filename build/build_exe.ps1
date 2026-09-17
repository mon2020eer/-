# =============================================================================
#  بناء نسخة ويندوز التنفيذية من منظومة إدارة مكتب إيجار السيارات
#
#  التشغيل من مجلد المشروع (PowerShell):
#      powershell -ExecutionPolicy Bypass -File build\build_exe.ps1
#
#  وعلى اتصال بطيء، للبناء بالمكتبات المثبّتة أصلاً بلا تنزيل جديد:
#      powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -NoVenv
#
#  الناتج: build\dist\CarRentalOffice\CarRentalOffice.exe
#
#  ⚠ هذا الملف محفوظ بترميز UTF-8 **مع علامة BOM**، ولا يجوز حفظه بغيرها.
#     Windows PowerShell 5.1 يقرأ ملفات .ps1 بلا BOM بترميز النظام العربي
#     (CP1256)، فتتحوّل الشدّة «ـّ» والشرطة «—» وعلامة «✓» إلى علامات اقتباس
#     ذكية يعدّها المفسّر بداية نصّ ونهايته، فينكسر السكربت برسالة
#     «Missing closing '}' in statement block».
# =============================================================================

param(
    # يبني بمكتبات بايثون المثبّتة على الجهاز بدل إنشاء بيئة افتراضية جديدة.
    # مفيد على اتصال بطيء: البيئة الجديدة تُعيد تنزيل Qt كاملاً (٥٨ ميغابايت).
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"

# PowerShell **لا يوقف** السكربت عند فشل أمر خارجي مثل pip مهما كان
# ErrorActionPreference: تلك الإعداد يخصّ أخطاء PowerShell نفسها لا رموز خروج
# البرامج. ولذلك مضى السكربت ذات مرّة بعد فشل تثبيت PyInstaller إلى تشغيل
# الاختبارات، فقال «فشلت الاختبارات» والاختبارات لم تُشغَّل أصلاً — ورسالة
# تُوجّه إلى المكان الخطأ أسوأ من رسالة صريحة.
function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    & $Action
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "✗ فشل: $Description" -ForegroundColor Red
        Write-Host "  راجع رسالة الخطأ أعلاه." -ForegroundColor Red
        exit 1
    }
}

$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

Write-Host "=== منظومة إدارة مكتب إيجار السيارات — بناء ملف التشغيل ===" -ForegroundColor Cyan
Write-Host "مجلد المشروع: $ProjectDir"

# --- 1) التحقّق من بايثون ---------------------------------------------------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "✗ لم يُعثر على بايثون. ثبّته من python.org وفعّل خيار Add to PATH." -ForegroundColor Red
    exit 1
}

$version = (python -c "import sys; print('%d.%d' % sys.version_info[:2])")
Write-Host "إصدار بايثون: $version"
if ([version]$version -lt [version]"3.9") {
    Write-Host "✗ يلزم بايثون 3.9 أو أحدث." -ForegroundColor Red
    exit 1
}

# --- 2) البيئة الافتراضية ---------------------------------------------------
if ($NoVenv) {
    Write-Host "-> البناء بمكتبات الجهاز (تُخطّيت البيئة الافتراضية)." -ForegroundColor Yellow
} else {
    if (-not (Test-Path ".venv")) {
        Write-Host "-> إنشاء بيئة افتراضية…" -ForegroundColor Yellow
        python -m venv .venv
    }
    & ".\.venv\Scripts\Activate.ps1"
}

# --- 3) المكتبات ------------------------------------------------------------
Write-Host "-> تثبيت المكتبات…" -ForegroundColor Yellow
if (-not $NoVenv) {
    Invoke-Step "تحديث pip" { python -m pip install --upgrade pip --quiet }
    Invoke-Step "تثبيت مكتبات التطبيق" {
        python -m pip install -r requirements.txt --quiet
    }
}

# PyInstaller **غير مثبَّت على رقم واحد** عمداً: النسخة المثبّتة تشترط إصدار
# بايثون بعينه، فتُرفض على كل بايثون أحدث منها («Could not find a version that
# satisfies the requirement»). والحدّ الأدنى ٦٫١٥ لأن ما دونه لا يدعم بايثون
# 3.14، والسقف على الإصدار الرئيسي لئلّا يكسر البناءَ صدورُ 7.x.
Invoke-Step "تثبيت PyInstaller و pytest" {
    python -m pip install "pyinstaller>=6.15,<7" pytest --quiet
}

# --- 4) الاختبارات قبل البناء ----------------------------------------------
# البناء على كود فاشل اختبارُه إهدار للوقت، ولذلك تُشغَّل الاختبارات أولاً.
Write-Host "-> تشغيل الاختبارات…" -ForegroundColor Yellow
$env:QT_QPA_PLATFORM = "offscreen"

# غياب pytest ليس فشلاً في الاختبارات بل في تثبيتها، والخلط بينهما يُرسل من
# يقرأ الرسالة إلى الشيفرة وهي سليمة.
python -c "import pytest" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ لم يُثبَّت pytest، فتعذّر تشغيل الاختبارات." -ForegroundColor Red
    Write-Host "  ثبّته يدوياً: python -m pip install pytest" -ForegroundColor Red
    exit 1
}

python -m pytest tests -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ فشلت الاختبارات — أُوقف البناء." -ForegroundColor Red
    exit 1
}
Remove-Item Env:\QT_QPA_PLATFORM

# --- 5) التنظيف ثم البناء ---------------------------------------------------
Write-Host "-> تنظيف مخرجات البناء السابقة…" -ForegroundColor Yellow
Remove-Item -Recurse -Force "build\dist", "build\work" -ErrorAction SilentlyContinue

Write-Host "-> بناء ملف التشغيل بـ PyInstaller…" -ForegroundColor Yellow

# **بـ `python -m` لا بالاسم المجرَّد**: pip يضع `pyinstaller.exe` في مجلد
# Scripts الخاصّ بالمستخدم، وهو ليس في PATH على كثير من أجهزة ويندوز (وتقول
# pip ذلك بتحذير صريح عند التثبيت). فالنداء بالاسم يسقط بـ
# «The term 'pyinstaller' is not recognized»، بينما `python -m` يستعمل
# المفسّر نفسه الذي ثُبّتت فيه الحزمة فلا يتعلّق بـ PATH إطلاقاً.
Invoke-Step "بناء ملف التشغيل" {
    python -m PyInstaller "build\car_rental.spec" --noconfirm `
        --distpath "build\dist" --workpath "build\work"
}

# --- 6) فحص الناتج ----------------------------------------------------------
$exePath = "build\dist\CarRentalOffice\CarRentalOffice.exe"
if (-not (Test-Path $exePath)) {
    Write-Host "✗ لم يُنتج ملف التشغيل." -ForegroundColor Red
    exit 1
}

$sizeMb = [math]::Round((Get-ChildItem "build\dist\CarRentalOffice" -Recurse |
                         Measure-Object -Property Length -Sum).Sum / 1MB, 1)

Write-Host ""
Write-Host "✓ اكتمل البناء بنجاح." -ForegroundColor Green
Write-Host "  الملف التنفيذي : $ProjectDir\$exePath"
Write-Host "  حجم المجلد     : $sizeMb ميغابايت"
Write-Host ""
Write-Host "لتوزيع التطبيق: انسخ مجلد build\dist\CarRentalOffice كاملاً،" -ForegroundColor Cyan
Write-Host "أو ابنِ مثبّتاً من build\installer.iss باستخدام Inno Setup." -ForegroundColor Cyan

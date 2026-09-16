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
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt --quiet
}
python -m pip install pyinstaller==6.10.0 pytest --quiet

# --- 4) الاختبارات قبل البناء ----------------------------------------------
# البناء على كود فاشل اختبارُه إهدار للوقت، ولذلك تُشغَّل الاختبارات أولاً.
Write-Host "-> تشغيل الاختبارات…" -ForegroundColor Yellow
$env:QT_QPA_PLATFORM = "offscreen"
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
pyinstaller "build\car_rental.spec" --noconfirm `
    --distpath "build\dist" --workpath "build\work"

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ فشل البناء." -ForegroundColor Red
    exit 1
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

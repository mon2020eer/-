# =============================================================================
#  توقيع ملفات المنظومة بشهادة ناشر — SignTool
#
#  لماذا التوقيع؟ ملفٌ غير موقَّع يستقبله ويندوز برسالة «SmartScreen منع تشغيل
#  تطبيقاً غير معروف»، ويستقبله مضادّ الفيروسات بالشكّ. والعميل الذي يرى هذه
#  الرسالة على برنامج دفع ثمنه لا يُطمْئنه شرحٌ بعدها.
#
#  والتوقيع **يُذكر فيه اسم الناشر: شركة المسار المتحد**، فيراه العميل في خانة
#  «الناشر» بدل «غير معروف».
#
#  الاستخدام:
#      # بشهادة مثبَّتة في مخزن ويندوز (الأفضل — لا يخرج المفتاح الخاص):
#      .\build\sign.ps1 -Thumbprint "A1B2C3..."
#
#      # أو بملف PFX:
#      .\build\sign.ps1 -PfxPath "C:\certs\masar.pfx" -PfxPassword "..."
#
#  يُنفَّذ **بعد** build_exe.ps1 و**قبل** بناء المثبّت، ثم مرّة أخرى على
#  المثبّت نفسه:
#      .\build\sign.ps1 -Thumbprint "..." -Path "build\installer\*.exe"
#
#  ⚠ الشهادة ملكٌ خاصّ: لا تُودَع في المستودع، ولا يُكتب رقمها هنا.
# =============================================================================

[CmdletBinding()]
param(
    # بصمة شهادة مثبَّتة في مخزن الشهادات الشخصي
    [string] $Thumbprint,

    # أو ملف شهادة PFX وكلمة سرّه
    [string] $PfxPath,
    [string] $PfxPassword,

    # ما يُوقَّع. الافتراضي: ملف التشغيل الناتج عن البناء
    [string] $Path = "build\dist\CarRentalOffice\CarRentalOffice.exe",

    # خادم الختم الزمني: بدونه يبطل التوقيع بانتهاء صلاحية الشهادة، ولو كان
    # الملف قد وُقِّع وهي سارية. وهذا يعني عميلاً يشتري اليوم ويرى تحذيراً
    # بعد سنتين على النسخة نفسها.
    [string] $TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

# --- هل توجد شهادة أصلاً؟ ---------------------------------------------------
# غيابها ليس فشلاً في البناء: المنظومة تعمل بلا توقيع، والتوقيع خطوة تجارية
# تأتي حين تُشترى الشهادة. فيخرج السكربت بنجاح شارحاً ما ينقص، ولا يكسر
# سلسلة البناء على جهاز لا شهادة فيه.
if (-not $Thumbprint -and -not $PfxPath) {
    Write-Host ""
    Write-Host "لم تُحدَّد شهادة توقيع — تُخطّى خطوة التوقيع." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "النسخة الناتجة تعمل كاملةً، لكن ويندوز سيعرض على العميل"
    Write-Host "تحذير «ناشر غير معروف» عند أول تشغيل."
    Write-Host ""
    Write-Host "لتوقيعها باسم «شركة المسار المتحد» تحتاج:"
    Write-Host "  1) شهادة Code Signing من جهة إصدار معتمدة"
    Write-Host "     (DigiCert أو Sectigo أو GlobalSign — تُصدر باسم الشركة"
    Write-Host "      وتتطلّب إثبات وجودها القانوني، وتستغرق أياماً)."
    Write-Host "  2) ثم:  .\build\sign.ps1 -Thumbprint ""بصمة الشهادة"""
    Write-Host ""
    exit 0
}

# --- العثور على signtool ----------------------------------------------------
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    # تأتي مع Windows SDK ولا تكون في PATH عادةً؛ يُبحث عن أحدث نسخة
    $candidates = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
        -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "x64" } |
        Sort-Object FullName -Descending
    if (-not $candidates) {
        Write-Error "لم يُعثر على signtool.exe. ثبّت Windows SDK ثم أعد المحاولة."
    }
    $signtool = $candidates[0]
}
$signtoolPath = if ($signtool.Source) { $signtool.Source } else { $signtool.FullName }

# --- ما الذي يُوقَّع؟ --------------------------------------------------------
$targets = Get-ChildItem $Path -ErrorAction SilentlyContinue
if (-not $targets) {
    Write-Error "لا ملفات للتوقيع في المسار: $Path`nشغّل build\build_exe.ps1 أولاً."
}

# --- التوقيع ----------------------------------------------------------------
# /fd sha256 و /td sha256: ويندوز الحديث يرفض SHA-1
$common = @("sign", "/fd", "sha256", "/tr", $TimestampUrl, "/td", "sha256", "/v")

foreach ($target in $targets) {
    Write-Host "توقيع: $($target.Name)" -ForegroundColor Cyan

    $arguments = $common + @()
    if ($Thumbprint) {
        $arguments += @("/sha1", $Thumbprint)
    } else {
        if (-not (Test-Path $PfxPath)) {
            Write-Error "ملف الشهادة غير موجود: $PfxPath"
        }
        $arguments += @("/f", $PfxPath)
        if ($PfxPassword) { $arguments += @("/p", $PfxPassword) }
    }
    $arguments += $target.FullName

    & $signtoolPath @arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Error "فشل توقيع $($target.Name) — رمز الخروج $LASTEXITCODE"
    }
}

# --- التحقّق ----------------------------------------------------------------
# التوقيع الذي لا يُتحقَّق منه وعدٌ لا برهان: قد ينجح الأمر وتبقى السلسلة ناقصة
foreach ($target in $targets) {
    & $signtoolPath "verify" "/pa" "/v" $target.FullName
    if ($LASTEXITCODE -ne 0) {
        Write-Error "التوقيع لم يُقبل عند التحقّق: $($target.Name)"
    }
}

Write-Host ""
Write-Host "تمّ التوقيع والتحقّق — الناشر: شركة المسار المتحد" -ForegroundColor Green

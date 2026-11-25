# =====================================================================
#  فحص الواي فاي بالبيت - سكربت Windows (بدون ذكاء اصطناعي)
#  التشغيل: دبل كلك على  wifi-check.bat  (اللي جنبه بنفس المجلد)
#  السكربت ما يغيّر اي اعداد ابداً. اي خطوة تفتح شي، يستأذنك قبلها.
# =====================================================================

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Add-Type -AssemblyName System.Net.Http

# ---------------------------- أدوات مساعدة ----------------------------
function Title($t)  { Write-Host ""; Write-Host ("=" * 60) -ForegroundColor DarkCyan; Write-Host "  $t" -ForegroundColor Cyan; Write-Host ("=" * 60) -ForegroundColor DarkCyan }
function Good($t)   { Write-Host "  [ممتاز] $t" -ForegroundColor Green }
function Warn($t)   { Write-Host "  [انتبه] $t" -ForegroundColor Yellow }
function Bad($t)    { Write-Host "  [مشكلة] $t" -ForegroundColor Red }
function Info($t)   { Write-Host "  $t" }
function AskYes($q) {
    $a = Read-Host "  $q (y = نعم / n = لا)"
    return ($a -match '^\s*(y|yes|ن|نعم|اي|ايه)\s*$')
}
function AskNumber($q, [switch]$AllowZero) {
    while ($true) {
        $a = "$(Read-Host "  $q")".Trim()
        # يقبل الارقام العربية بعد
        $a = [regex]::Replace($a, '[\u0660-\u0669]', { param($m) [string]([int][char]$m.Value - 0x0660) })
        $n = 0.0
        if ([double]::TryParse($a, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$n) -and ($n -gt 0 -or ($AllowZero -and $n -eq 0))) { return $n }
        Warn "اكتب رقم بس، مثال: 100"
    }
}
function Mbps($bytes, $seconds) { if ($seconds -le 0) { return 0 }; return [math]::Round(($bytes * 8) / $seconds / 1e6, 1) }

# حقول netsh (تدعم ويندوز انجليزي، واذا اللغة غير يحاول بالارقام)
function NetshField($lines, $names) {
    foreach ($l in $lines) {
        foreach ($n in $names) {
            if ($l -match "^\s*$n\s*:\s*(.+)$") { return $Matches[1].Trim() }
        }
    }
    return $null
}

Clear-Host
Title "فحص الواي فاي بالبيت"
Info "هالسكربت يفحص اتصالك ويشرح لك النتيجة ببساطة."
Info "ما راح يغيّر اي اعداد بجهازك او الراوتر. اي شي يفتحه يستأذنك قبل."
Info "خل الجهاز شابك على واي فاي البيت، وسكّر التحميلات والفيديو قبل لا تبدأ."
Read-Host "  اضغط Enter للبدء"

# ======================= 1) سرعة الباقة =======================
Title "1) سرعة باقتك"
$plan = AskNumber "كم سرعة باقتك بالميغابت؟ (مكتوبة بالفاتورة او العقد، مثال 100 او 500)"
Info "تمام، باقتك $plan ميغابت."

# ======================= 2) معلومات الواي فاي =======================
Title "2) معلومات اتصال الواي فاي"
$wl = @(netsh wlan show interfaces 2>$null)
$ssid    = NetshField $wl @('SSID')
$signal  = $null
foreach ($l in $wl) { if ($l -match ':\s*(\d{1,3})\s*%') { $signal = [int]$Matches[1]; break } }
$myChan  = NetshField $wl @('Channel')
$radio   = NetshField $wl @('Radio type')
$bandTxt = NetshField $wl @('Band')
$rxRate  = NetshField $wl @('Receive rate \(Mbps\)')

$wifiAdapter = Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and ($_.MediaType -match '802\.11' -or $_.PhysicalMediaType -match '802\.11|Wireless') } | Select-Object -First 1
$linkMbps = $null
if ($wifiAdapter) { $linkMbps = [math]::Round($wifiAdapter.ReceiveLinkSpeed / 1e6) }
elseif ($rxRate) { $linkMbps = [double]$rxRate }

if (-not $wifiAdapter -and -not $signal) {
    Bad "ما لقيت اتصال واي فاي شغّال. اذا انت شابك بكيبل، الفحص بيكمل بس قسم الواي فاي ما راح يطلع."
} else {
    if ($ssid)   { Info "اسم الشبكة: $ssid" }
    $myChanNum = 0; [int]::TryParse("$myChan", [ref]$myChanNum) | Out-Null
    $myBand = ''
    if ($bandTxt) { $myBand = $bandTxt }
    elseif ($myChanNum -ge 1 -and $myChanNum -le 14) { $myBand = '2.4 GHz' }
    elseif ($myChanNum -gt 14) { $myBand = '5 GHz' }
    if ($myChan) { Info "القناة: $myChan   النطاق: $myBand   النوع: $radio" }
    if ($linkMbps) { Info "سرعة الربط بين جهازك والراوتر: $linkMbps ميغابت" }
    if ($signal -ne $null) {
        if     ($signal -ge 75) { Good "قوة الاشارة $signal% - قوية" }
        elseif ($signal -ge 50) { Warn "قوة الاشارة $signal% - متوسطة" }
        else                    { Bad  "قوة الاشارة $signal% - ضعيفة" }
    }
    if (-not $myChan) {
        Warn "ما قدرت اقرا رقم القناة (يمكن لغة الويندوز مو انجليزي). هذي المعلومات الخام:"
        $wl | Where-Object { $_ -match ':' } | ForEach-Object { Info "   $_" }
    }
}

# ======================= 3) البرامج اللي تستهلك النت =======================
Title "3) البرامج اللي تستهلك النت بالخلفية"
$bgMbps = $null
$adapterForStats = if ($wifiAdapter) { $wifiAdapter } else { Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -First 1 }
if ($adapterForStats) {
    Info "اقيس استهلاك جهازك الحين لمدة 5 ثواني (لا تستخدم النت)..."
    $s1 = Get-NetAdapterStatistics -Name $adapterForStats.Name
    Start-Sleep -Seconds 5
    $s2 = Get-NetAdapterStatistics -Name $adapterForStats.Name
    $bgMbps = Mbps (($s2.ReceivedBytes - $s1.ReceivedBytes) + ($s2.SentBytes - $s1.SentBytes)) 5
    if     ($bgMbps -lt 1) { Good "جهازك تقريباً ما يستهلك شي بالخلفية ($bgMbps ميغابت)" }
    elseif ($bgMbps -lt 5) { Warn "فيه استهلاك خفيف بالخلفية: $bgMbps ميغابت" }
    else                   { Bad  "فيه استهلاك واضح بالخلفية: $bgMbps ميغابت - شي قاعد يحمّل او يرفع" }
}

Info ""
Info "البرامج اللي فاتحة اتصالات اكثر شي بالنت:"
$conns = Get-NetTCPConnection -State Established | Where-Object { $_.RemoteAddress -notmatch '^(127\.|::1|0\.0\.0\.0)' }
$top = $conns | Group-Object OwningProcess | Sort-Object Count -Descending | Select-Object -First 8
$topNames = @()
foreach ($g in $top) {
    $p = Get-Process -Id ([int]$g.Name)
    $name = if ($p) { $p.ProcessName } else { "PID $($g.Name)" }
    $topNames += $name
    Info ("   - {0,-28} {1} اتصال" -f $name, $g.Count)
}

$heavy = @{
  'OneDrive'='ون درايف (مزامنة ملفات)'; 'Dropbox'='دروب بوكس'; 'GoogleDriveFS'='قوقل درايف'
  'steam'='ستيم (تحديث العاب)'; 'steamwebhelper'='ستيم'; 'EpicGamesLauncher'='ايبك قيمز'
  'Battle.net'='باتل نت'; 'qbittorrent'='تورنت'; 'uTorrent'='تورنت'; 'BitTorrent'='تورنت'
  'Teams'='تيمز'; 'ms-teams'='تيمز'; 'Zoom'='زووم'; 'Spotify'='سبوتيفاي'
  'MoUsoCoreWorker'='تحديث ويندوز'; 'TiWorker'='تحديث ويندوز'; 'iCloudDrive'='اي كلاود'
  'EADesktop'='EA'; 'Origin'='اوريجن'; 'XboxPcApp'='اكس بوكس'; 'Creative Cloud'='ادوبي'
}
$found = @()
foreach ($k in $heavy.Keys) { if (Get-Process -Name $k) { $found += "$k ($($heavy[$k]))" } }
if ($found.Count) {
    Warn "برامج معروفة انها تسحب نت بالخلفية وهي شغالة الحين:"
    $found | Sort-Object -Unique | ForEach-Object { Info "   - $_" }
} else { Good "ما لقيت برامج تحميل او مزامنة معروفة شغالة." }
Info "(عشان تشوف كم كل برنامج يسحب بالضبط: مراقب الموارد > تبويب Network)"
$bgApp = if ($found.Count) { ($found | Select-Object -First 1) } elseif ($topNames.Count) { $topNames[0] } else { $null }

# ======================= 4) اختبار السرعة =======================
Title "4) اختبار السرعة"
$gw = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1).NextHop
function PingStats($target, $count) {
    $p = New-Object System.Net.NetworkInformation.Ping
    $times = @(); $lost = 0
    for ($i = 0; $i -lt $count; $i++) {
        try { $r = $p.Send($target, 1500); if ($r.Status -eq 'Success') { $times += $r.RoundtripTime } else { $lost++ } } catch { $lost++ }
        Start-Sleep -Milliseconds 200
    }
    $avg = if ($times.Count) { [math]::Round(($times | Measure-Object -Average).Average) } else { $null }
    $jit = 0
    if ($times.Count -gt 1) { $d = for ($i = 1; $i -lt $times.Count; $i++) { [math]::Abs($times[$i] - $times[$i-1]) }; $jit = [math]::Round(($d | Measure-Object -Average).Average) }
    return @{ Avg = $avg; Jitter = $jit; Loss = [math]::Round(100 * $lost / $count) }
}
Info "اقيس الاستجابة (البنق)..."
$pingGw  = if ($gw) { PingStats $gw 10 } else { $null }
$pingNet = PingStats '1.1.1.1' 10

$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(60)
$streams = 4

Info "اقيس سرعة التحميل (حوالي 15 ثانية)..."
$down = 0
try {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $tasks = 1..$streams | ForEach-Object { $client.GetByteArrayAsync("https://speed.cloudflare.com/__down?bytes=25000000") }
    [Threading.Tasks.Task]::WaitAll($tasks)
    $sw.Stop()
    $bytes = ($tasks | ForEach-Object { $_.Result.Length } | Measure-Object -Sum).Sum
    $down = Mbps $bytes $sw.Elapsed.TotalSeconds
} catch { $down = 0 }

Info "اقيس سرعة الرفع..."
$up = 0
try {
    $payload = New-Object byte[] 8000000
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $tasks = 1..$streams | ForEach-Object { $client.PostAsync("https://speed.cloudflare.com/__up", ([System.Net.Http.ByteArrayContent]::new($payload))) }
    [Threading.Tasks.Task]::WaitAll($tasks)
    $sw.Stop()
    $up = Mbps ($payload.Length * $streams) $sw.Elapsed.TotalSeconds
} catch { $up = 0 }

Info ""
if ($down -le 0) {
    Bad "ما قدرت اكمل اختبار السرعة. يمكن النت مقطوع."
} else {
    $ratio = [math]::Round(100 * $down / $plan)
    Info "التحميل: $down ميغابت   (باقتك $plan = تحصل $ratio% منها)"
    Info "الرفع:   $up ميغابت"
    if ($pingNet.Avg) { Info "البنق للنت: $($pingNet.Avg) ms   التذبذب: $($pingNet.Jitter) ms   الفاقد: $($pingNet.Loss)%" }
    if ($pingGw -and $pingGw.Avg -ne $null) { Info "البنق للراوتر: $($pingGw.Avg) ms   الفاقد: $($pingGw.Loss)%" }
    Info ""
    if     ($ratio -ge 80) { Good "السرعة ممتازة مقارنة بباقتك." }
    elseif ($ratio -ge 50) { Warn "السرعة مقبولة، بس اقل من باقتك بشكل ملحوظ." }
    else                   { Bad  "السرعة اقل من نص باقتك." }
}

# ======================= 5) زحمة القنوات =======================
Title "5) هل قناة الواي فاي مزدحمة؟"
$nl = @(netsh wlan show networks mode=bssid 2>$null)
$nets = @(); $curSsid = ''; $cur = $null
foreach ($l in $nl) {
    if ($l -match '^SSID \d+ : ?(.*)$') { $curSsid = $Matches[1].Trim(); continue }
    if ($l -match '^\s+BSSID \d+\s*:') { if ($cur) { $nets += $cur }; $cur = @{ Ssid = $curSsid; Signal = 0; Chan = 0; Band = '' }; continue }
    if ($cur) {
        if ($l -match '^\s+Signal\s*:\s*(\d+)%')  { $cur.Signal = [int]$Matches[1] }
        elseif ($l -match '^\s+Channel\s*:\s*(\d+)') { $cur.Chan = [int]$Matches[1] }
        elseif ($l -match '^\s+Band\s*:\s*(.+)$')    { $cur.Band = $Matches[1].Trim() }
    }
}
if ($cur) { $nets += $cur }
foreach ($n in $nets) { if (-not $n.Band) { $n.Band = if ($n.Chan -le 14) { '2.4 GHz' } else { '5 GHz' } } }

$crowded = $false; $bestChan = $null; $has5g = $false; $neighbours = 0
if (-not $nets.Count) {
    Warn "ما قدرت اقرا الشبكات اللي حولك."
    Info "بويندوز 11: فعّل (خدمات الموقع) من الاعدادات > الخصوصية > الموقع، وشغّل السكربت مرة ثانية."
} elseif (-not $myChanNum) {
    Info "لقيت $($nets.Count) شبكة حولك، بس ما اعرف قناتك عشان اقارن."
} else {
    $others = $nets | Where-Object { $_.Ssid -ne $ssid -and $_.Signal -ge 30 }
    $is24 = $myChanNum -le 14
    if ($is24) {
        $same = $others | Where-Object { $_.Chan -le 14 -and [math]::Abs($_.Chan - $myChanNum) -lt 5 }
        $neighbours = @($same).Count
        Info "شبكات الجيران القوية اللي تتداخل مع قناتك ($myChanNum): $neighbours"
        $scores = @{}
        foreach ($c in 1, 6, 11) { $scores[$c] = @($others | Where-Object { $_.Chan -le 14 -and [math]::Abs($_.Chan - $c) -lt 5 }).Count }
        $bestChan = ($scores.GetEnumerator() | Sort-Object Value | Select-Object -First 1).Key
        Info ("عدد الشبكات على القنوات 1 / 6 / 11:  {0} / {1} / {2}" -f $scores[1], $scores[6], $scores[11])
        $crowded = $neighbours -ge 5 -and $bestChan -ne $myChanNum -and $scores[$bestChan] -lt $neighbours
        # هل نفس الراوتر يبث 5 جيجا؟
        $has5g = @($nets | Where-Object { $_.Chan -gt 14 -and ($_.Ssid -eq $ssid -or $_.Ssid -like "$ssid*5G*" -or $_.Ssid -like "$ssid*5*") }).Count -gt 0
    } else {
        $same = $others | Where-Object { $_.Chan -eq $myChanNum }
        $neighbours = @($same).Count
        Info "شبكات الجيران القوية على نفس قناتك ($myChanNum): $neighbours"
        $cands = 36, 40, 44, 48, 149, 153, 157, 161
        $bestChan = $cands | Sort-Object { $c = $_; @($others | Where-Object { $_.Chan -eq $c }).Count } | Select-Object -First 1
        $crowded = $neighbours -ge 3 -and @($others | Where-Object { $_.Chan -eq $bestChan }).Count -lt $neighbours
    }
    if ($crowded) { Bad "قناتك مزدحمة. القناة الاهدى حولك: $bestChan" }
    else          { Good "قناتك مو مزدحمة." }
    if ($is24 -and $has5g) { Warn "راوترك يبث 5 جيجا بعد، وانت شابك على 2.4 (الابطأ)." }
}

# ======================= 6) الاجهزة المتصلة =======================
Title "6) الاجهزة المتصلة بالراوتر"
if ($gw) {
    $prefix = ($gw -split '\.')[0..2] -join '.'
    $seen = Get-NetNeighbor -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "$prefix.*" -and $_.State -in 'Reachable','Stale','Delay','Probe' -and $_.IPAddress -ne "$prefix.255" }
    Info "عنوان الراوتر: $gw"
    Info "جهازك شاف تقريباً $(@($seen).Count) جهاز على الشبكة مؤخراً (هذا رقم تقريبي، اللستة الكاملة بصفحة الراوتر)."
    Info ""
    Info "كيف تقرا لستة الاجهزة من الراوتر:"
    Info "  1. افتح المتصفح على:  http://$gw"
    Info "  2. اسم المستخدم وكلمة السر مكتوبين على ملصق تحت الراوتر (غالباً admin)."
    Info "  3. دوّر على قسم اسمه وحدة من هذي:"
    Info "     Connected Devices / Attached Devices / DHCP Clients / Device List / Client List"
    Info "  4. كل سطر = جهاز. قارن الاسماء مع اجهزتك (جوالات، تلفزيون، بلايستيشن، كاميرات...)."
    Info "  5. لا تغيّر شي بالصفحة، بس اقرا."
    if (AskYes "تبيني افتح صفحة الراوتر بالمتصفح الحين؟") { Start-Process "http://$gw" }
    $devCount = AskNumber "كم جهاز لقيت باللستة؟ (اكتب رقم، او 0 اذا ما قدرت تدخل)" -AllowZero
} else { Warn "ما لقيت عنوان الراوتر."; $devCount = 0 }
$unknown = $false
if ($devCount -gt 0) {
    $unknown = -not (AskYes "تعرف كل الاجهزة اللي باللستة؟")
    if ($devCount -ge 15) { Warn "$devCount جهاز عدد كبير، كلهم يتقاسمون نفس الباقة." }
    if ($unknown) { Bad "فيه اجهزة ما تعرفها. ممكن احد يستخدم شبكتك." }
}

# ======================= 7) الخلاصة =======================
Title "7) الخلاصة ببساطة"
if ($down -gt 0) { Info "- النت يوصلك $down من $plan ميغابت ($ratio%)." }
if ($signal -ne $null) { Info "- الاشارة $signal% $(if($signal -ge 75){'قوية'}elseif($signal -ge 50){'متوسطة'}else{'ضعيفة'})." }
if ($bgMbps -ne $null) { Info "- جهازك يستهلك بالخلفية $bgMbps ميغابت." }
if ($myChanNum) { Info "- قناتك $myChanNum $(if($crowded){'مزدحمة'}else{'مرتاحة'})." }
if ($linkMbps -and $linkMbps -lt $plan) { Info "- سرعة الربط مع الراوتر ($linkMbps) اقل من باقتك، يعني الواي فاي نفسه هو السقف." }

# اختيار تعديل واحد بس، حسب الاهمية
$tip = $null; $why = $null; $action = $null
if ($down -le 0) {
    $tip = "طفّي الراوتر 30 ثانية وشغّله، وانتظر دقيقتين وعيد الفحص."
    $why = "اختبار السرعة ما اشتغل، يعني الاتصال بالنت نفسه فيه مشكلة."
} elseif ($unknown) {
    $tip = "غيّر كلمة سر الواي فاي من صفحة الراوتر (قسم Wireless / Security)."
    $why = "فيه اجهزة ما تعرفها، وكل جهاز غريب ياخذ من سرعتك."; $action = 'router'
} elseif ($signal -ne $null -and $signal -lt 50) {
    $tip = "قرّب من الراوتر، او حط الراوتر بمكان عالي ووسط البيت بعيد عن الجدران والمطبخ."
    $why = "اشارتك ضعيفة ($signal%)، وهذا اكبر سبب للبطء."
} elseif ($bgMbps -ge 5 -or ($bgMbps -gt 0 -and $bgMbps -ge 0.2 * $plan)) {
    $tip = "وقّف او أجّل البرنامج اللي يحمّل بالخلفية" + $(if ($bgApp) { ": $bgApp" } else { "" }) + "."
    $why = "جهازك يسحب $bgMbps ميغابت بدون ما تستخدمه."; $action = 'resmon'
} elseif ($has5g -and $myBand -like '2.4*') {
    $tip = "اشبك على شبكة الـ 5 جيجا بدل 2.4 (غالباً نفس الاسم او فيه 5G)."
    $why = "2.4 جيجا ابطأ وازحم، و5 جيجا اسرع بكثير وانت قريب من الراوتر."; $action = 'wifi'
} elseif ($crowded) {
    $tip = "غيّر قناة الواي فاي بالراوتر الى القناة $bestChan (قسم Wireless > Channel)."
    $why = "قناتك عليها $neighbours شبكة جيران تزاحمك."; $action = 'router'
} elseif ($ratio -lt 50) {
    $tip = "جرّب كيبل مباشر من الراوتر للجهاز وعيد الفحص. اذا بقت بطيئة كلّم شركة الاتصالات."
    $why = "الاشارة والقناة زينة، بس السرعة اقل من نص الباقة، فالمشكلة غالباً من الخط."
} else {
    $tip = "ما تحتاج تغيّر شي. بس خل الراوتر بمكان عالي ومكشوف."
    $why = "كل شي ضمن الطبيعي."
}

Write-Host ""
Write-Host "  >> التعديل اللي اقترح تجربه:" -ForegroundColor Magenta
Write-Host "     $tip" -ForegroundColor White
Write-Host "     السبب: $why" -ForegroundColor Gray
Write-Host ""

# السكربت ما يغيّر شي بنفسه - بس يفتح لك المكان المناسب اذا وافقت
switch ($action) {
    'router' { if ($gw -and (AskYes "تبيني افتح صفحة الراوتر عشان تسوي التعديل بنفسك؟")) { Start-Process "http://$gw"; Info "ملاحظة: بعد الحفظ الراوتر ممكن يفصل دقيقة، عادي." } }
    'resmon' { if (AskYes "تبيني افتح مراقب الموارد عشان تشوف البرنامج وتقفله بنفسك؟") { Start-Process resmon } }
    'wifi'   { if (AskYes "تبيني افتح قائمة شبكات الواي فاي؟") { Start-Process "ms-availablenetworks:" } }
}

Info "بعد ما تجرب التعديل، شغّل الفحص مرة ثانية وقارن."
Read-Host "  اضغط Enter للخروج"

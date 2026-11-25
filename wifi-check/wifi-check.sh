#!/usr/bin/env bash
# =====================================================================
#  فحص الواي فاي بالبيت - سكربت ماك ولينكس (بدون ذكاء اصطناعي)
#  التشغيل:  bash wifi-check.sh
#  السكربت ما يغيّر اي اعداد ابداً. اي خطوة تفتح شي، يستأذنك قبلها.
# =====================================================================

OS="$(uname -s)"
C0=$'\e[0m'; CC=$'\e[36m'; CG=$'\e[32m'; CY=$'\e[33m'; CR=$'\e[31m'; CM=$'\e[35m'
title() { echo; echo "${CC}============================================================"; echo "  $1"; echo "============================================================${C0}"; }
good()  { echo "  ${CG}[ممتاز] $1${C0}"; }
warn()  { echo "  ${CY}[انتبه] $1${C0}"; }
bad()   { echo "  ${CR}[مشكلة] $1${C0}"; }
info()  { echo "  $1"; }
ask_yes() {
  local a; read -r -p "  $1 (y = نعم / n = لا) " a
  [[ "$a" =~ ^[[:space:]]*(y|Y|yes|ن|نعم|اي|ايه)[[:space:]]*$ ]]
}
# ask_number "سؤال" [allow_zero]
ask_number() {
  local a
  while true; do
    read -r -p "  $1 " a || { echo; exit 1; }
    a="$(echo "$a" | sed -e 's/٠/0/g;s/١/1/g;s/٢/2/g;s/٣/3/g;s/٤/4/g;s/٥/5/g;s/٦/6/g;s/٧/7/g;s/٨/8/g;s/٩/9/g' | tr -d ' \t\r')"
    if [[ "$a" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
      if [[ -n "$2" ]] || awk "BEGIN{exit !($a>0)}"; then echo "$a"; return; fi
    fi
    warn "اكتب رقم بس، مثال: 100" >&2
  done
}
calc()  { awk "BEGIN{printf \"%.1f\", $1}"; }
ge()    { awk "BEGIN{exit !($1>=$2)}"; }
lt()    { awk "BEGIN{exit !($1<$2)}"; }
open_url() { if [[ "$OS" == "Darwin" ]]; then open "$1"; else xdg-open "$1" >/dev/null 2>&1 & fi; }

clear
title "فحص الواي فاي بالبيت"
info "هالسكربت يفحص اتصالك ويشرح لك النتيجة ببساطة."
info "ما راح يغيّر اي اعداد بجهازك او الراوتر. اي شي يفتحه يستأذنك قبل."
info "خل الجهاز شابك على واي فاي البيت، وسكّر التحميلات والفيديو قبل لا تبدأ."
read -r -p "  اضغط Enter للبدء "

# ======================= 1) سرعة الباقة =======================
title "1) سرعة باقتك"
PLAN="$(ask_number "كم سرعة باقتك بالميغابت؟ (مكتوبة بالفاتورة او العقد، مثال 100 او 500)")"
info "تمام، باقتك $PLAN ميغابت."

# ======================= 2) معلومات الواي فاي =======================
title "2) معلومات اتصال الواي فاي"
SSID=""; SIGNAL=""; MYCHAN=""; LINK=""; NEIGH_CHANS=""   # NEIGH_CHANS: سطر لكل شبكة "قناة اشارة% اسم"
if [[ "$OS" == "Darwin" ]]; then
  SP="$(system_profiler SPAirPortDataType 2>/dev/null)"
  CUR="$(echo "$SP" | awk '/Current Network Information:/{f=1;next} /Other Local Wi-Fi Networks:/{f=0} f')"
  SSID="$(echo "$CUR" | awk 'NR==1{gsub(/^[ \t]+|:$/,""); print}')"
  MYCHAN="$(echo "$CUR" | awk -F': ' '/Channel:/{split($2,a," "); print a[1]; exit}')"
  DBM="$(echo "$CUR" | awk -F': ' '/Signal \/ Noise:/{split($2,a," "); print a[1]; exit}')"
  [[ -n "$DBM" ]] && SIGNAL="$(awk "BEGIN{p=2*($DBM+100); if(p>100)p=100; if(p<0)p=0; printf \"%d\", p}")"
  LINK="$(echo "$CUR" | awk -F': ' '/Transmit Rate:/{print $2; exit}')"
  NEIGH_CHANS="$(echo "$SP" | awk '
    /Other Local Wi-Fi Networks:/{f=1;next}
    f && NF { match($0,/^ */); ind=RLENGTH; if (ind<12) f=0 }
    f && ind==12 && /:$/ {name=$0; gsub(/^[ \t]+|:$/,"",name)}
    f && /Channel:/ {split($0,a,": "); split(a[2],b," "); ch=b[1]}
    f && /Signal \/ Noise:/ {split($0,a,": "); split(a[2],b," "); p=2*(b[1]+100); if(p>100)p=100; if(p<0)p=0; print ch, int(p), name}
')"
elif command -v nmcli >/dev/null; then
  LIST="$(nmcli -t -f IN-USE,SSID,CHAN,SIGNAL,RATE dev wifi list 2>/dev/null)"
  MINE="$(echo "$LIST" | grep '^\*' | head -1)"
  if [[ -n "$MINE" ]]; then
    SSID="$(echo "$MINE" | cut -d: -f2)"; MYCHAN="$(echo "$MINE" | cut -d: -f3)"
    SIGNAL="$(echo "$MINE" | cut -d: -f4)"; LINK="$(echo "$MINE" | cut -d: -f5 | tr -dc '0-9')"
  fi
  NEIGH_CHANS="$(echo "$LIST" | grep -v '^\*' | awk -F: '{print $3, $4, $2}')"
fi

BAND=""
if [[ -n "$MYCHAN" ]]; then if (( MYCHAN <= 14 )); then BAND="2.4 GHz"; else BAND="5 GHz"; fi; fi
if [[ -z "$SIGNAL" && -z "$MYCHAN" ]]; then
  bad "ما لقيت اتصال واي فاي (او ما قدرت اقراه). الفحص بيكمل بس قسم الواي فاي ما راح يطلع."
else
  [[ -n "$SSID" ]] && info "اسم الشبكة: $SSID"
  [[ -n "$MYCHAN" ]] && info "القناة: $MYCHAN   النطاق: $BAND"
  [[ -n "$LINK" ]] && info "سرعة الربط بين جهازك والراوتر: $LINK ميغابت"
  if [[ -n "$SIGNAL" ]]; then
    if   (( SIGNAL >= 75 )); then good "قوة الاشارة $SIGNAL% - قوية"
    elif (( SIGNAL >= 50 )); then warn "قوة الاشارة $SIGNAL% - متوسطة"
    else bad "قوة الاشارة $SIGNAL% - ضعيفة"; fi
  fi
fi

# ======================= 3) البرامج اللي تستهلك النت =======================
title "3) البرامج اللي تستهلك النت بالخلفية"
info "اقيس استهلاك جهازك الحين لمدة 5 ثواني (لا تستخدم النت)..."
BG=""; TOPAPP=""
if [[ "$OS" == "Darwin" ]]; then
  NT="$(nettop -P -L 2 -d -x -s 5 -J bytes_in,bytes_out 2>/dev/null | awk -F, '
    /bytes_in/ {n++; for(i=1;i<=NF;i++) if($i=="bytes_in") bi=i; next}
    n==2 && bi>1 && $(bi-1)!="" {print $(bi-1)","($bi+$(bi+1))}')"
  # الاسم بصيغة name.pid
  BG="$(echo "$NT" | awk -F, '{s+=$2} END{printf "%.1f", s*8/5/1e6}')"
  info ""; info "اكثر البرامج استهلاك خلال الخمس ثواني:"
  echo "$NT" | sort -t, -k2 -nr | head -8 | awk -F, '$2>0{n=$1; sub(/\.[0-9]+$/,"",n); printf "     - %-28s %.2f ميغابت\n", n, $2*8/5/1e6}'
  TOPAPP="$(echo "$NT" | sort -t, -k2 -nr | awk -F, '$2>0{n=$1; sub(/\.[0-9]+$/,"",n); print n; exit}')"
else
  IFACE="$(ip route 2>/dev/null | awk '/^default/{print $5; exit}')"
  if [[ -n "$IFACE" && -r /sys/class/net/$IFACE/statistics/rx_bytes ]]; then
    r1=$(cat /sys/class/net/$IFACE/statistics/rx_bytes); t1=$(cat /sys/class/net/$IFACE/statistics/tx_bytes)
    sleep 5
    r2=$(cat /sys/class/net/$IFACE/statistics/rx_bytes); t2=$(cat /sys/class/net/$IFACE/statistics/tx_bytes)
    BG="$(calc "(($r2-$r1)+($t2-$t1))*8/5/1e6")"
  fi
  info ""; info "البرامج اللي فاتحة اتصالات اكثر شي بالنت:"
  ss -tnpH state established 2>/dev/null | grep -o 'users:(("[^"]*"' | sed 's/users:(("//; s/"$//' \
    | sort | uniq -c | sort -nr | head -8 | awk '{printf "     - %-28s %s اتصال\n", $2, $1}'
  TOPAPP="$(ss -tnpH state established 2>/dev/null | grep -o 'users:(("[^"]*"' | sed 's/users:(("//; s/"$//' | sort | uniq -c | sort -nr | awk '{print $2; exit}')"
  command -v nethogs >/dev/null && info "(لتشوف استهلاك كل برنامج بالضبط شغّل:  sudo nethogs)"
fi
if [[ -n "$BG" ]]; then
  if   lt "$BG" 1; then good "جهازك تقريباً ما يستهلك شي بالخلفية ($BG ميغابت)"
  elif lt "$BG" 5; then warn "فيه استهلاك خفيف بالخلفية: $BG ميغابت"
  else bad "فيه استهلاك واضح بالخلفية: $BG ميغابت - شي قاعد يحمّل او يرفع"; fi
fi
FOUND=""
for p in OneDrive Dropbox "Google Drive" Steam steam qbittorrent transmission-gtk Transmission uTorrent Teams "Microsoft Teams" zoom.us zoom Spotify spotify "Creative Cloud" Battle.net EpicGamesLauncher; do
  pgrep -xi "$p" >/dev/null 2>&1 && FOUND="$FOUND $p"
done
if [[ -n "$FOUND" ]]; then warn "برامج معروفة انها تسحب نت بالخلفية وهي شغالة:$FOUND"
else good "ما لقيت برامج تحميل او مزامنة معروفة شغالة."; fi

# ======================= 4) اختبار السرعة =======================
title "4) اختبار السرعة"
if [[ "$OS" == "Darwin" ]]; then GW="$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')"
else GW="$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')"; fi

ping_stats() {  # يطبع: متوسط فاقد%
  local out; out="$(ping -c 10 -i 0.2 "$1" 2>/dev/null || ping -c 10 "$1" 2>/dev/null)"
  local avg loss
  avg="$(echo "$out" | awk -F'/' '/min\/avg|round-trip/{printf "%d", $5}')"
  loss="$(echo "$out" | grep -o '[0-9.]*% packet loss' | cut -d% -f1)"
  echo "${avg:-0} ${loss:-100}"
}
info "اقيس الاستجابة (البنق)..."
read -r PING_NET LOSS_NET <<<"$(ping_stats 1.1.1.1)"
[[ -n "$GW" ]] && read -r PING_GW LOSS_GW <<<"$(ping_stats "$GW")"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
info "اقيس سرعة التحميل (حوالي 15 ثانية)..."
for i in 1 2 3 4; do
  curl -s -o /dev/null --max-time 60 -w '%{size_download} %{time_total}\n' "https://speed.cloudflare.com/__down?bytes=25000000" > "$TMP/d$i" &
done; wait
DOWN="$(cat "$TMP"/d* | awk '{b+=$1; if($2>t)t=$2} END{if(t>0) printf "%.1f", b*8/t/1e6; else print 0}')"

info "اقيس سرعة الرفع..."
head -c 8000000 /dev/zero > "$TMP/up.bin"
for i in 1 2 3 4; do
  curl -s -o /dev/null --max-time 60 --data-binary @"$TMP/up.bin" -w '%{size_upload} %{time_total}\n' "https://speed.cloudflare.com/__up" > "$TMP/u$i" &
done; wait
UP="$(cat "$TMP"/u* | awk '{b+=$1; if($2>t)t=$2} END{if(t>0) printf "%.1f", b*8/t/1e6; else print 0}')"

echo
RATIO=0
if ! ge "$DOWN" 0.1; then
  bad "ما قدرت اكمل اختبار السرعة. يمكن النت مقطوع."
else
  RATIO="$(awk "BEGIN{printf \"%d\", 100*$DOWN/$PLAN}")"
  info "التحميل: $DOWN ميغابت   (باقتك $PLAN = تحصل $RATIO% منها)"
  info "الرفع:   $UP ميغابت"
  info "البنق للنت: ${PING_NET} ms   الفاقد: ${LOSS_NET}%"
  [[ -n "$GW" ]] && info "البنق للراوتر: ${PING_GW} ms   الفاقد: ${LOSS_GW}%"
  echo
  if   (( RATIO >= 80 )); then good "السرعة ممتازة مقارنة بباقتك."
  elif (( RATIO >= 50 )); then warn "السرعة مقبولة، بس اقل من باقتك بشكل ملحوظ."
  else bad "السرعة اقل من نص باقتك."; fi
fi

# ======================= 5) زحمة القنوات =======================
title "5) هل قناة الواي فاي مزدحمة؟"
CROWDED=""; BEST=""; NEIGH=0; HAS5G=""
if [[ -z "$NEIGH_CHANS" ]]; then
  warn "ما قدرت اقرا الشبكات اللي حولك."
  [[ "$OS" == "Darwin" ]] && info "بالماك الجديد: اسمح للطرفية بخدمات الموقع (الاعدادات > الخصوصية > خدمات الموقع)."
elif [[ -z "$MYCHAN" ]]; then
  info "لقيت شبكات حولك، بس ما اعرف قناتك عشان اقارن."
else
  STRONG="$(echo "$NEIGH_CHANS" | awk -v me="$SSID" '$2>=30 && $3!=me')"
  if (( MYCHAN <= 14 )); then
    NEIGH="$(echo "$STRONG" | awk -v c="$MYCHAN" '$1>0 && $1<=14 {d=$1-c; if(d<0)d=-d; if(d<5)n++} END{print n+0}')"
    info "شبكات الجيران القوية اللي تتداخل مع قناتك ($MYCHAN): $NEIGH"
    read -r S1 S6 S11 <<<"$(echo "$STRONG" | awk '$1>0 && $1<=14 {for(i=1;i<=3;i++){c=(i==1?1:(i==2?6:11)); d=$1-c; if(d<0)d=-d; if(d<5)s[i]++}} END{print s[1]+0, s[2]+0, s[3]+0}')"
    info "عدد الشبكات على القنوات 1 / 6 / 11:  $S1 / $S6 / $S11"
    BEST=1; BS=$S1
    (( S6 < BS )) && { BEST=6; BS=$S6; }
    (( S11 < BS )) && { BEST=11; BS=$S11; }
    (( NEIGH >= 5 && BEST != MYCHAN && BS < NEIGH )) && CROWDED=1
    [[ -n "$SSID" ]] && echo "$NEIGH_CHANS" | awk -v me="$SSID" '$1>14 && index($0, me)>0' | grep -q . && HAS5G=1
  else
    NEIGH="$(echo "$STRONG" | awk -v c="$MYCHAN" '$1==c{n++} END{print n+0}')"
    info "شبكات الجيران القوية على نفس قناتك ($MYCHAN): $NEIGH"
    BEST=36; BS=999
    for c in 36 40 44 48 149 153 157 161; do
      n="$(echo "$STRONG" | awk -v c="$c" '$1==c{n++} END{print n+0}')"
      (( n < BS )) && { BEST=$c; BS=$n; }
    done
    (( NEIGH >= 3 && BS < NEIGH )) && CROWDED=1
  fi
  if [[ -n "$CROWDED" ]]; then bad "قناتك مزدحمة. القناة الاهدى حولك: $BEST"; else good "قناتك مو مزدحمة."; fi
  [[ -n "$HAS5G" && "$BAND" == "2.4 GHz" ]] && warn "راوترك يبث 5 جيجا بعد، وانت شابك على 2.4 (الابطأ)."
fi

# ======================= 6) الاجهزة المتصلة =======================
title "6) الاجهزة المتصلة بالراوتر"
DEVS=0; UNKNOWN=""
if [[ -n "$GW" ]]; then
  PREFIX="${GW%.*}"
  SEEN="$(arp -an 2>/dev/null | grep -F "($PREFIX." | grep -v -e incomplete -e "($PREFIX.255)" | wc -l | tr -d ' ')"
  info "عنوان الراوتر: $GW"
  info "جهازك شاف تقريباً $SEEN جهاز على الشبكة مؤخراً (رقم تقريبي، اللستة الكاملة بصفحة الراوتر)."
  echo
  info "كيف تقرا لستة الاجهزة من الراوتر:"
  info "  1. افتح المتصفح على:  http://$GW"
  info "  2. اسم المستخدم وكلمة السر مكتوبين على ملصق تحت الراوتر (غالباً admin)."
  info "  3. دوّر على قسم اسمه وحدة من هذي:"
  info "     Connected Devices / Attached Devices / DHCP Clients / Device List / Client List"
  info "  4. كل سطر = جهاز. قارن الاسماء مع اجهزتك (جوالات، تلفزيون، بلايستيشن، كاميرات...)."
  info "  5. لا تغيّر شي بالصفحة، بس اقرا."
  ask_yes "تبيني افتح صفحة الراوتر بالمتصفح الحين؟" && open_url "http://$GW"
  DEVS="$(ask_number "كم جهاز لقيت باللستة؟ (اكتب رقم، او 0 اذا ما قدرت تدخل)" zero)"
else
  warn "ما لقيت عنوان الراوتر."
fi
if ge "$DEVS" 1; then
  ask_yes "تعرف كل الاجهزة اللي باللستة؟" || UNKNOWN=1
  ge "$DEVS" 15 && warn "$DEVS جهاز عدد كبير، كلهم يتقاسمون نفس الباقة."
  [[ -n "$UNKNOWN" ]] && bad "فيه اجهزة ما تعرفها. ممكن احد يستخدم شبكتك."
fi

# ======================= 7) الخلاصة =======================
title "7) الخلاصة ببساطة"
ge "$DOWN" 0.1 && info "- النت يوصلك $DOWN من $PLAN ميغابت ($RATIO%)."
if [[ -n "$SIGNAL" ]]; then
  if (( SIGNAL >= 75 )); then s="قوية"; elif (( SIGNAL >= 50 )); then s="متوسطة"; else s="ضعيفة"; fi
  info "- الاشارة $SIGNAL% $s."
fi
[[ -n "$BG" ]] && info "- جهازك يستهلك بالخلفية $BG ميغابت."
[[ -n "$MYCHAN" ]] && info "- قناتك $MYCHAN $([[ -n "$CROWDED" ]] && echo مزدحمة || echo مرتاحة)."
[[ -n "$LINK" ]] && lt "$LINK" "$PLAN" && info "- سرعة الربط مع الراوتر ($LINK) اقل من باقتك، يعني الواي فاي نفسه هو السقف."

# اختيار تعديل واحد بس، حسب الاهمية
ACTION=""
if ! ge "$DOWN" 0.1; then
  TIP="طفّي الراوتر 30 ثانية وشغّله، وانتظر دقيقتين وعيد الفحص."
  WHY="اختبار السرعة ما اشتغل، يعني الاتصال بالنت نفسه فيه مشكلة."
elif [[ -n "$UNKNOWN" ]]; then
  TIP="غيّر كلمة سر الواي فاي من صفحة الراوتر (قسم Wireless / Security)."
  WHY="فيه اجهزة ما تعرفها، وكل جهاز غريب ياخذ من سرعتك."; ACTION=router
elif [[ -n "$SIGNAL" ]] && (( SIGNAL < 50 )); then
  TIP="قرّب من الراوتر، او حط الراوتر بمكان عالي ووسط البيت بعيد عن الجدران والمطبخ."
  WHY="اشارتك ضعيفة ($SIGNAL%)، وهذا اكبر سبب للبطء."
elif [[ -n "$BG" ]] && { ge "$BG" 5 || ge "$BG" "$(calc "0.2*$PLAN")"; } && ge "$BG" 0.5; then
  APP="${TOPAPP:-$(echo "$FOUND" | awk '{print $1}')}"
  TIP="وقّف او أجّل البرنامج اللي يحمّل بالخلفية${APP:+: $APP}."
  WHY="جهازك يسحب $BG ميغابت بدون ما تستخدمه."; ACTION=apps
elif [[ -n "$HAS5G" && "$BAND" == "2.4 GHz" ]]; then
  TIP="اشبك على شبكة الـ 5 جيجا بدل 2.4 (غالباً نفس الاسم او فيه 5G)."
  WHY="2.4 جيجا ابطأ وازحم، و5 جيجا اسرع بكثير وانت قريب من الراوتر."; ACTION=wifi
elif [[ -n "$CROWDED" ]]; then
  TIP="غيّر قناة الواي فاي بالراوتر الى القناة $BEST (قسم Wireless > Channel)."
  WHY="قناتك عليها $NEIGH شبكة جيران تزاحمك."; ACTION=router
elif (( RATIO < 50 )); then
  TIP="جرّب كيبل مباشر من الراوتر للجهاز وعيد الفحص. اذا بقت بطيئة كلّم شركة الاتصالات."
  WHY="الاشارة والقناة زينة، بس السرعة اقل من نص الباقة، فالمشكلة غالباً من الخط."
else
  TIP="ما تحتاج تغيّر شي. بس خل الراوتر بمكان عالي ومكشوف."
  WHY="كل شي ضمن الطبيعي."
fi

echo
echo "  ${CM}>> التعديل اللي اقترح تجربه:${C0}"
echo "     $TIP"
echo "     السبب: $WHY"
echo

# السكربت ما يغيّر شي بنفسه - بس يفتح لك المكان المناسب اذا وافقت
case "$ACTION" in
  router) [[ -n "$GW" ]] && ask_yes "تبيني افتح صفحة الراوتر عشان تسوي التعديل بنفسك؟" && { open_url "http://$GW"; info "ملاحظة: بعد الحفظ الراوتر ممكن يفصل دقيقة، عادي."; } ;;
  apps)   if [[ "$OS" == "Darwin" ]]; then ask_yes "تبيني افتح مراقب النشاط (تبويب الشبكة) عشان تقفل البرنامج بنفسك؟" && open -a "Activity Monitor"
          else info "تقدر تقفله من مدير المهام، او تشوف التفاصيل بـ: sudo nethogs"; fi ;;
  wifi)   if [[ "$OS" == "Darwin" ]]; then ask_yes "تبيني افتح اعدادات الواي فاي؟" && open "x-apple.systempreferences:com.apple.wifi-settings-extension"
          else info "اختار شبكة الـ 5 جيجا من ايقونة الواي فاي فوق."; fi ;;
esac

info "بعد ما تجرب التعديل، شغّل الفحص مرة ثانية وقارن."

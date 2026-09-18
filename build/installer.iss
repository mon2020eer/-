; =============================================================================
;  مثبّت ويندوز لمنظومة إدارة مكتب إيجار السيارات — Inno Setup
;
;  الاستخدام:
;    1) نفّذ build\build_exe.ps1 أولاً لإنتاج مجلد build\dist\CarRentalOffice
;    2) ثبّت Inno Setup من https://jrsoftware.org/isinfo.php
;    3) افتح هذا الملف فيه واضغط Build، أو من سطر الأوامر:
;       iscc build\installer.iss
;
;  الناتج: build\installer\CarRentalOffice-Setup.exe
; =============================================================================

#define AppName "منظومة إدارة مكتب إيجار السيارات"
#define AppNameEn "CarRentalOffice"
#define AppVersion "1.2.0"
#define AppExe "CarRentalOffice.exe"
#define AppPublisher "شركة المسار المتحد"

[Setup]
; ============================ الترقية فوق القديم ============================
;  AppId **لا يُغيَّر أبداً**. هو ما يعرف به ويندوز أن هذا التثبيت هو نفسه
;  التثبيت السابق، فيُرقّيه في مكانه بدل أن يضع نسخةً ثانية بجانبه. وتغييرُه
;  يعني عميلاً بنسختين على قائمة البرامج، يفتح إحداهما فلا يجد بياناته.
;
;  وبيانات المكتب أصلاً خارج مجلد البرنامج (%APPDATA%\CarRentalOffice)، وتُرقّى
;  قاعدتها تلقائياً عند أوّل تشغيل بعد نسخةٍ احتياطية تسبق الترقية.
;  التفاصيل في docs\UPGRADE.md
; ===========================================================================
AppId={{8B3F1C24-7E4A-4D96-9C41-2A6F0B5D7E13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName}
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
OutputDir=installer
OutputBaseFilename={#AppNameEn}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; يسمح بالتثبيت دون صلاحيات المدير، فيُستخدم على أجهزة المكتب العادية
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; مجلد البناء كاملاً: ملف التشغيل ومكتبات Qt وملفات المخطط والنمط
Source: "dist\{#AppNameEn}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; الأدلّة العربية تُثبَّت بجانب التطبيق
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\دليل المستخدم"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\دليل الترقية"; Filename: "{app}\docs\UPGRADE.md"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

; ملاحظة مهمّة: بيانات التطبيق (قاعدة البيانات والمرفقات) تُحفظ في
; %APPDATA%\CarRentalOffice ولا تُحذف عند إزالة التطبيق — وهذا مقصود
; حمايةً لبيانات المكتب من الضياع بإزالة تثبيت عرضية.

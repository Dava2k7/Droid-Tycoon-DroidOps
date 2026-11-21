#define MyAppName "Droid Tycoon DroidOps"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.54"
#endif
#define MyAppPublisher "Danksy"
#define MyAppExeName "DroidTycoonDroidOps.exe"
#define MyAppUserModelID "DaneVanzino.DroidTycoonAutoClickerV1"

[Setup]
AppId={{E6DC5CFB-DB93-4E3D-8BF5-B7CE535C4D3D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Danksy\DroidOps
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=Danksy_DroidOps_{#MyAppVersion}_Setup
SetupIconFile=..\droidops\assets\app.ico
UninstallDisplayIcon={app}\app.ico
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "driver"; Description: "Install or repair ViGEmBus controller driver"; Flags: unchecked

[Files]
Source: "..\dist\DroidTycoonDroidOps\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\droidops\assets\app.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Collect-Diagnostics.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\Collect-Diagnostics.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\docs\RESTART_DIAGNOSTICS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "ViGEmBus_1.22.0_x64_x86_arm64.exe"; DestDir: "{app}\Driver"; Flags: ignoreversion
Source: "ViGEmBus-LICENSE.txt"; DestDir: "{app}\Driver"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"; AppUserModelID: "{#MyAppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\Driver\ViGEmBus_1.22.0_x64_x86_arm64.exe"; Description: "Install ViGEmBus"; Tasks: driver; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

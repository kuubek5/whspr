; kuubwave.iss — Inno Setup script. Packages the PyInstaller one-folder build
; (dist\KuubWave) into a single per-user installer (no admin / UAC prompt).
;
; Build:  iscc packaging\kuubwave.iss   (after running the PyInstaller build)
; Output: packaging\Output\kuubwave-setup.exe

#define AppName "KuubWave"
; build.ps1 passes the real version from flow.APP_VERSION via /DAppVersion; this
; is only the fallback when ISCC is run by hand without that override.
#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#define AppPublisher "KuubWave"
#define AppExe "KuubWave.exe"

[Setup]
; Unchanged across the whspr -> KuubWave rename ON PURPOSE: Inno identifies an
; installation by AppId, so a new GUID would install a second copy alongside the
; old one instead of upgrading it in place.
AppId={{8F1D3B2A-7C4E-4A9B-9E21-0A1B2C3D4E5F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; per-user install -> no admin rights needed
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
; Versioned filename. A fixed "kuubwave-setup.exe" silently overwrote the previous
; build, so two installers with different contents could both claim 1.1.0 with
; nothing on disk to tell them apart — and check_update(), which compares
; versions, would not see the newer one as newer.
OutputBaseFilename=kuubwave-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "startup"; Description: "Запускати KuubWave при вході в Windows"; Flags: unchecked

[Files]
; the entire PyInstaller output folder
Source: "..\dist\KuubWave\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустити KuubWave"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; remove per-user data (config/db/log/models/cuda) on uninstall
Type: filesandordirs; Name: "{localappdata}\KuubWave"
; The pre-rename folder. flow._migrate_data_dir normally MOVES it away, but its
; cross-volume fallback copies and leaves the original behind, so uninstall has
; to clean up both names to keep its "removes per-user data" promise.
Type: filesandordirs; Name: "{localappdata}\whspr"

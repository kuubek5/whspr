; whspr.iss — Inno Setup script. Packages the PyInstaller one-folder build
; (dist\whspr) into a single per-user installer (no admin / UAC prompt).
;
; Build:  iscc packaging\whspr.iss   (after running the PyInstaller build)
; Output: packaging\Output\whspr-setup.exe

#define AppName "whspr"
#define AppVersion "1.0.0"
#define AppPublisher "whspr"
#define AppExe "whspr.exe"

[Setup]
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
OutputBaseFilename=whspr-setup
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
Name: "startup"; Description: "Запускати whspr при вході в Windows"; Flags: unchecked

[Files]
; the entire PyInstaller output folder
Source: "..\dist\whspr\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустити whspr"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; remove per-user data (config/db/log/models/cuda) on uninstall
Type: filesandordirs; Name: "{localappdata}\whspr"

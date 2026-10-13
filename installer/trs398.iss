; Inno Setup 6:  ISCC.exe /DAppVersion=2.0.0 installer\trs398.iss   (needs build\dist\TRS398 made by tools\build_windows.py)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1E8C52-7E3A-4D0B-9F1C-5A3D9E2B7F10}
AppName=TRS-398
AppVersion={#AppVersion}
AppPublisher=TRS-398 platform
DefaultDirName={autopf}\TRS398
DefaultGroupName=TRS-398
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\build
OutputBaseFilename=TRS398-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=TRS-398
CloseApplications=yes
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "autostart"; Description: "Запускать вместе с Windows / Start with Windows"; Flags: unchecked

[Files]
Source: "..\build\dist\TRS398\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\TRS-398"; Filename: "{app}\TRS398.exe"
Name: "{autodesktop}\TRS-398"; Filename: "{app}\TRS398.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TRS398"; ValueData: """{app}\TRS398.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\TRS398.exe"; Description: "Запустить TRS-398 / Launch TRS-398"; Flags: nowait postinstall skipifsilent

; The data (%LOCALAPPDATA%\TRS398\data) are NOT removed by the uninstaller.

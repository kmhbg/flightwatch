; Inno Setup script: per-user install (no admin rights), Start menu entry, optional autostart.
;   iscc /DAppVersion=0.2.0 packaging\windows\flightwatch.iss    (after pyinstaller, from the repo root)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1E8E3A-5C2F-4F7B-9A3D-2E4C8F1A7B90}
AppName=Flightwatch
AppVersion={#AppVersion}
AppPublisher=Flightwatch
DefaultDirName={localappdata}\Programs\Flightwatch
DefaultGroupName=Flightwatch
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Flightwatch-{#AppVersion}-windows-setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\Flightwatch.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "sv"; MessagesFile: "compiler:Languages\Swedish.isl"

[CustomMessages]
en.AutoStart=Start Flightwatch when I log in
sv.AutoStart=Starta Flightwatch vid inloggning

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStart}"

[Files]
Source: "..\..\dist\Flightwatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Flightwatch"; Filename: "{app}\Flightwatch.exe"
Name: "{userdesktop}\Flightwatch"; Filename: "{app}\Flightwatch.exe"; Tasks: desktopicon

[Registry]
; The app manages this value itself (settings → autostart); the installer sets the initial choice and
; the uninstaller removes it.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Flightwatch"; \
  ValueData: """{app}\Flightwatch.exe"" app --background"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Flightwatch"; \
  Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\Flightwatch.exe"; Description: "{cm:LaunchProgram,Flightwatch}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im Flightwatch.exe /f"; Flags: runhidden; RunOnceId: "StopFlightwatch"

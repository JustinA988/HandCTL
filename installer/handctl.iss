; Inno Setup script for handctl. Don't compile this directly: run installer\build.ps1, which freezes the app
; first and passes the version from pyproject.toml.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{DE044EBF-FB78-4D53-9B46-38BCFE6DFC7B}
AppName=handctl
AppVersion={#AppVersion}
AppPublisher=handctl contributors
AppPublisherURL=https://github.com/JustinA988/HandCTL
DefaultDirName={autopf}\handctl
DisableProgramGroupPage=yes
; installs for the current user without admin rights; the setup offers an all-users install as an option
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\LICENSE
OutputDir=..\build\installer
OutputBaseFilename=handctl-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; the app holds this mutex while running (handctl/__main__.py), so setup and uninstall ask to close it first
AppMutex=handctl-single-instance
CloseApplications=yes
UninstallDisplayIcon={app}\handctl.exe

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
Name: autostart; Description: "Start handctl when Windows starts"; Flags: unchecked

[Files]
Source: "..\build\dist\handctl\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\handctl"; Filename: "{app}\handctl.exe"
Name: "{autodesktop}\handctl"; Filename: "{app}\handctl.exe"; Tasks: desktopicon

[Registry]
; same value the app's own "Start with Windows" setting writes, so the two stay in step
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "handctl"; ValueData: """{app}\handctl.exe"" --tray"; Flags: uninsdeletevalue; Tasks: autostart
; on uninstall, also remove it if it was turned on later from the app's settings
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "handctl"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\handctl.exe"; Description: "Start handctl now"; Flags: nowait postinstall skipifsilent

; Settings in %APPDATA%\handctl are left in place on uninstall, so a reinstall keeps your calibration.

; Inno Setup script for the Lethal Cuts installer. packaging\build.py runs this with the
; version and folders filled in, e.g.  ISCC /DAppVersion=0.1.0 /DSourceDir=... /DOutputDir=... installer.iss
;
; Installs for the current user only (no admin password needed) into
; %LOCALAPPDATA%\Programs\Lethal Cuts, with a desktop shortcut. A newer installer with the
; same AppId replaces the old version. Settings (%APPDATA%\Lethal Cuts) and the .lcproj
; files next to videos are never touched, so updates keep them.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3C2A51-9B7E-4D2C-A8E1-4C1D5B7A9E30}
AppName=Lethal Cuts
AppVersion={#AppVersion}
AppVerName=Lethal Cuts {#AppVersion}
AppPublisher=Lethal Cuts
DefaultDirName={localappdata}\Programs\Lethal Cuts
DefaultGroupName=Lethal Cuts
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=Lethal Cuts Setup {#AppVersion}
SetupIconFile={#SourceDir}\icon.ico
UninstallDisplayIcon={app}\Lethal Cuts.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a Lethal Cuts shortcut on the desktop"; GroupDescription: "Shortcuts:"

[InstallDelete]
; Clear out the old program files on update, so nothing stale is left behind.
; (Only the program folder: settings and projects live elsewhere.)
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Lethal Cuts"; Filename: "{app}\Lethal Cuts.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Check that Lethal Cuts works"; Filename: "{app}\Lethal Cuts.exe"; Parameters: "--check"; IconFilename: "{app}\icon.ico"
Name: "{userdesktop}\Lethal Cuts"; Filename: "{app}\Lethal Cuts.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\Lethal Cuts.exe"; Description: "Start Lethal Cuts now"; Flags: nowait postinstall skipifsilent

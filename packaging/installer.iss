; Inno Setup script for the Lethal Cuts installer. packaging\build.py runs this with the
; version and folders filled in, e.g.  ISCC /DAppVersion=0.3.0 /DSourceDir=... /DOutputDir=... installer.iss
;
; Installs for the current user only (no admin password needed). The person picks the install
; folder (default %LOCALAPPDATA%\Programs\Lethal Cuts) and a folder for their videos.
; The program itself goes in a "program" subfolder, and only that subfolder is cleared on
; updates, so videos saved anywhere else (even in the install folder itself) are never touched.
; Uninstalling removes only the files this installer put there.
; Run with /SILENT /RESTART (what the in-app Update button does) to update quietly and reopen the program.
; /SAVEDIR=<folder> picks the video folder without asking.

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
; The folder page shows on a first install; updates go into the same folder without asking.
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=Lethal Cuts Setup {#AppVersion}
SetupIconFile={#SourceDir}\icon.ico
UninstallDisplayIcon={app}\program\Lethal Cuts.exe
UninstallDisplayName=Lethal Cuts
UninstallFilesDir={app}\program
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
; Only the "program" subfolder: the person's videos are never in there.
Type: filesandordirs; Name: "{app}\program\*"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}\program"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; In the install folder itself: open the program, or uninstall it
Name: "{app}\Lethal Cuts"; Filename: "{app}\program\Lethal Cuts.exe"; IconFilename: "{app}\program\icon.ico"
Name: "{app}\Uninstall Lethal Cuts"; Filename: "{uninstallexe}"; Comment: "Removes the program. Your videos are kept."
Name: "{group}\Lethal Cuts"; Filename: "{app}\program\Lethal Cuts.exe"; IconFilename: "{app}\program\icon.ico"
Name: "{group}\Check that Lethal Cuts works"; Filename: "{app}\program\Lethal Cuts.exe"; Parameters: "--check"; IconFilename: "{app}\program\icon.ico"
Name: "{group}\Uninstall Lethal Cuts"; Filename: "{uninstallexe}"; Comment: "Removes the program. Your videos are kept."
Name: "{userdesktop}\Lethal Cuts"; Filename: "{app}\program\Lethal Cuts.exe"; IconFilename: "{app}\program\icon.ico"; Tasks: desktopicon

[UninstallDelete]
; Written by this installer below, so it's removed with the program
Type: files; Name: "{app}\program\install.ini"

[Run]
Filename: "{app}\program\Lethal Cuts.exe"; Description: "Start Lethal Cuts now"; Flags: nowait postinstall skipifsilent
; After an update from inside the program, reopen it
Filename: "{app}\program\Lethal Cuts.exe"; Flags: nowait; Check: IsRestart

[Code]
var
  SavePage: TInputDirWizardPage;

function IsRestart: Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), '/RESTART') = 0 then
      Result := True;
end;

// /SAVEDIR=<folder> sets the video folder without asking (used by tests and silent installs)
function SaveDirParam: String;
var
  i: Integer;
begin
  Result := '';
  for i := 1 to ParamCount do
    if CompareText(Copy(ParamStr(i), 1, 9), '/SAVEDIR=') = 0 then
      Result := Copy(ParamStr(i), 10, Length(ParamStr(i)));
end;

procedure InitializeWizard;
begin
  SavePage := CreateInputDirPage(wpSelectDir,
    'Where to save your videos',
    'Lethal Cuts keeps your recordings, Shorts and long videos in one folder.',
    'Pick the folder for your videos, then click Next. You can change it later in the program''s Settings.' + #13#10#13#10 +
    'Uninstalling or updating Lethal Cuts never deletes anything in this folder.',
    False, 'New Folder');
  SavePage.Add('');
  SavePage.Values[0] := GetPreviousData('SaveFolder', ExpandConstant('{%USERPROFILE}\Videos\Lethal Cuts'));
  if SaveDirParam <> '' then
    SavePage.Values[0] := SaveDirParam;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // Updates keep the folder picked the first time
  Result := (PageID = SavePage.ID) and (GetPreviousData('SaveFolder', '') <> '');
end;

function CanWriteTo(Folder: String): Boolean;
var
  Test: String;
begin
  Result := ForceDirectories(Folder);
  if Result then
  begin
    Test := AddBackslash(Folder) + 'lethal-cuts-write-test.tmp';
    Result := SaveStringToFile(Test, 'test', False);
    DeleteFile(Test);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ProgramDir: String;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not CanWriteTo(WizardDirValue) then
  begin
    MsgBox('Windows doesn''t let programs install in that folder without an admin password.' + #13#10 +
           'Pick another folder, such as the one it suggested.', mbError, MB_OK);
    Result := False;
  end;
  if CurPageID = SavePage.ID then
  begin
    ProgramDir := Lowercase(AddBackslash(WizardDirValue) + 'program\');
    if Pos(ProgramDir, Lowercase(AddBackslash(SavePage.Values[0]))) = 1 then
    begin
      MsgBox('That''s inside the program''s own files, which get replaced on every update.' + #13#10 +
             'Pick a different folder for your videos (the install folder itself is fine).', mbError, MB_OK);
      Result := False;
    end
    else if not CanWriteTo(SavePage.Values[0]) then
    begin
      MsgBox('Lethal Cuts can''t save in that folder. Pick another one.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'SaveFolder', SavePage.Values[0]);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(SavePage.Values[0]);
    SetArrayLength(Lines, 2);
    Lines[0] := '[Lethal Cuts]';
    Lines[1] := 'SaveFolder=' + SavePage.Values[0];
    SaveStringsToUTF8File(ExpandConstant('{app}\program\install.ini'), Lines, False);
  end;
end;

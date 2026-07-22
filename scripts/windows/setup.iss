; ==========================================================================
;  Seed Code - Inno Setup script (one-click public-release installer)
;
;  Packages the standalone dist\seedcode.exe (built by build.bat stage 1).
;  The exe is fully self-contained (PyInstaller bundles Python + every
;  dependency), so the end user needs NOTHING pre-installed: download
;  SeedCodeSetup.exe, run it, done.
;
;    * modern branded wizard (Seed Code icon, wizard art, license page)
;    * no Python required, detected, or downloaded on the user's PC
;    * installs into Program Files, adds the folder to the system PATH
;    * Start Menu shortcut always, Desktop shortcut optional - all with the
;      Seed Code icon (never the default Python icon)
;    * verifies TWICE before claiming success: the installed exe reports
;      exactly this installer's version, and `seedcode` resolves through
;      PATH the way a NEW terminal will see it; failure aborts loudly
;    * offers to launch Seed Code when setup finishes
;    * uninstaller removes exe/shortcuts/PATH and ASKS before deleting user
;      data (settings, API keys, chat history, logs)
;
;  Compile:  build.bat   (or:  iscc /ORelease setup.iss  from scripts\windows)
;  Output:   Release\SeedCodeSetup.exe
; ==========================================================================

#define MyAppName "Seed Code"
; build.bat injects the version it verified against the freshly built exe
; (/DAppVersionFromBuild=...), so installer metadata can never disagree with
; the packaged binary. The fallback below is only for manual ISCC runs.
#ifdef AppVersionFromBuild
  #define MyAppVersion AppVersionFromBuild
#else
  #define MyAppVersion "1.2.0.3"
#endif
; Refuse to compile without the build outputs - packaging nothing (or a
; leftover) must fail loudly, not "succeed".
#if !FileExists(AddBackslash(SourcePath) + "..\..\dist\seedcode.exe")
  #error "dist\seedcode.exe not found - run scripts\windows\build.bat"
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\..\assets\windows\seedcode.ico")
  #error "assets\windows\seedcode.ico not found - run: python scripts\windows\build_assets.py"
#endif
#define MyAppPublisher "Al Shahriar Sowan"
#define MyAppURL "https://github.com/Alshahriar-07/seedcode-cli"
#define MyAppExeName "seedcode.exe"

[Setup]
; A stable AppId ties installs/upgrades/uninstalls together. Keep it constant.
AppId={{7B2C4E10-9F3A-4B6D-8C21-3E5A1D9F0C77}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
DefaultDirName={autopf}\SeedCode
DefaultGroupName={#MyAppName}
; One-click flow: skip the Start Menu group page (sane default is used) so a
; user who accepts defaults clicks License -> Install -> Finish and is done.
DisableProgramGroupPage=yes
; Branding: the setup.exe itself, the wizard pages, and Add/Remove Programs
; all use the Seed Code artwork - the default icon never appears.
SetupIconFile=..\..\assets\windows\seedcode.ico
WizardImageFile=..\..\assets\windows\wizard.bmp
WizardSmallImageFile=..\..\assets\windows\wizard-small.bmp
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\seedcode.ico
; Default output; build.bat overrides with /O to target the repo-root Release\.
OutputDir=..\..\Release
OutputBaseFilename=SeedCodeSetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
; Declaring PATH changes makes Windows broadcast WM_SETTINGCHANGE when setup
; finishes, so NEW terminal sessions see the updated PATH immediately.
ChangesEnvironment=yes
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The self-contained CLI produced by PyInstaller - all Python dependencies
; are already bundled inside it, so end users need nothing else to RUN it.
Source: "..\..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; The icon ships alongside the exe so every shortcut and the Add/Remove
; Programs entry reference the same authoritative .ico file.
Source: "..\..\assets\windows\seedcode.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; IconFilename pins every shortcut to the Seed Code .ico explicitly (belt and
; braces on top of the icon PyInstaller embeds into the exe itself).
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\seedcode.ico"; Comment: "Plant ideas. Grow code."
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\seedcode.ico"; Tasks: desktopicon

[Registry]
; Append {app} to the system PATH only when it is not already present, so the
; `seedcode` command resolves from any directory in any new shell.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
; postinstall entries run as the ORIGINAL (non-elevated) user by default, so
; Seed Code starts under the logged-in account and onboarding writes to THAT
; user's ~\.seedcode - a fresh profile gets the full first-run wizard
; (provider -> API key -> model), with no provider/model/history preset.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[Code]
// ---------------------------------------------------------------------------
// PATH management
// ---------------------------------------------------------------------------
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  // Wrap in semicolons so partial directory names never match by accident.
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

// On uninstall, strip the app directory back out of the system PATH.
procedure RemovePath(Param: string);
var
  OrigPath: string;
  NewPath: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath) then
    exit;

  NewPath := ';' + OrigPath + ';';
  P := Pos(';' + Uppercase(Param) + ';', Uppercase(NewPath));
  if P > 0 then
  begin
    Delete(NewPath, P, Length(Param) + 1);
    if (Length(NewPath) > 0) and (NewPath[1] = ';') then
      Delete(NewPath, 1, 1);
    if (Length(NewPath) > 0) and (NewPath[Length(NewPath)] = ';') then
      Delete(NewPath, Length(NewPath), 1);
    RegWriteExpandStringValue(HKLM,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path', NewPath);
  end;
end;

// ---------------------------------------------------------------------------
// Install verification (mandatory - a failure aborts, never false success)
// ---------------------------------------------------------------------------
// Two independent probes, both required:
//   1. The INSTALLED exe reports exactly this installer's version (exit code
//      0 alone would also pass for a stale binary; the version string proves
//      the packaged exe is the one this setup was built against).
//   2. Bare `seedcode --version` resolves through PATH exactly as a NEW
//      terminal will see it (the fresh {app} entry is appended for the probe
//      because this process still holds the pre-install environment).
function VersionReportOk(const Command: string; var Reported: string): Boolean;
var
  ResultCode: Integer;
  VerFile: string;
  Output: AnsiString;
begin
  Result := False;
  VerFile := ExpandConstant('{tmp}\seedcode-version.txt');
  // cmd /C "<command> > <file> 2>&1" - one outer quote pair; inner quotes
  // (around the exe path) are preserved by cmd's quote-stripping rules.
  if not Exec(ExpandConstant('{cmd}'),
      '/C "' + Command + ' > "' + VerFile + '" 2>&1"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    Log(Format('"%s" exited with code %d', [Command, ResultCode]));
    exit;
  end;
  if not LoadStringFromFile(VerFile, Output) then
    exit;
  Reported := Trim(String(Output));
  Result := Pos('v{#MyAppVersion}', Reported) > 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Reported: string;
begin
  if CurStep = ssPostInstall then
  begin
    // Probe 1: the installed binary itself.
    WizardForm.StatusLabel.Caption := 'Verifying the installed program...';
    Reported := '(no output)';
    if not VersionReportOk(
        '"' + ExpandConstant('{app}\{#MyAppExeName}') + '" --version', Reported) then
    begin
      Log('Exe verification FAILED. Output: ' + Reported);
      SuppressibleMsgBox(
        'Installation verification FAILED.' + #13#10#13#10 +
        'The installed seedcode.exe did not report version {#MyAppVersion} ' +
        '(it said: "' + Reported + '").' + #13#10#13#10 +
        'The copied program is incomplete or damaged. Try running the ' +
        'installer again; if it keeps failing, report it at {#MyAppURL}.',
        mbCriticalError, MB_OK, IDOK);
      Abort;
    end;
    Log('Exe verification passed: ' + Reported);

    // Probe 2: the `seedcode` command as a NEW terminal will resolve it.
    // This process still has the old PATH, so append {app} for the probe -
    // the registry entry written above gives new shells the same view.
    WizardForm.StatusLabel.Caption := 'Verifying the seedcode command...';
    Reported := '(no output)';
    if not VersionReportOk(
        'set "PATH=%PATH%;' + ExpandConstant('{app}') + '" && seedcode --version',
        Reported) then
    begin
      Log('PATH verification FAILED. Output: ' + Reported);
      SuppressibleMsgBox(
        'Seed Code was installed, but the "seedcode" command could not be ' +
        'verified (output: "' + Reported + '").' + #13#10#13#10 +
        'Another program named seedcode may be shadowing it on PATH. ' +
        'You can still start Seed Code from the Start Menu shortcut. ' +
        'If the command does not work in a new terminal, report it at ' +
        '{#MyAppURL}.',
        mbCriticalError, MB_OK, IDOK);
      Abort;
    end;
    Log('PATH verification passed: ' + Reported);
  end;
end;

// ---------------------------------------------------------------------------
// Uninstall: PATH cleanup always; user data only after explicit consent
// ---------------------------------------------------------------------------
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemovePath(ExpandConstant('{app}'));

    // Settings, API keys, chat history, and logs all live in ~\.seedcode.
    // Never delete silently: they may be shared with a pip-installed copy.
    DataDir := ExpandConstant('{%USERPROFILE}\.seedcode');
    if DirExists(DataDir) then
    begin
      if SuppressibleMsgBox(
        'Also remove your Seed Code data?' + #13#10#13#10 +
        'This deletes settings, API keys, chat history, and logs at:' + #13#10 +
        DataDir + #13#10#13#10 +
        'Choose No to keep them for a future installation.',
        mbConfirmation, MB_YESNO, IDNO) = IDYES then
      begin
        if DelTree(DataDir, True, True, True) then
          Log('User data removed: ' + DataDir)
        else
          SuppressibleMsgBox(
            'Some Seed Code data could not be removed. Delete this folder ' +
            'manually if desired: ' + DataDir, mbInformation, MB_OK, IDOK);
      end
      else
        Log('User data kept at ' + DataDir);
    end;
  end;
end;

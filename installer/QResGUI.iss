; QRes GUI setup: release\QResGUI-<version>-setup.exe, for winget and anyone who
; prefers an installer to a zip.
;
; It installs exactly the way install.cmd does - it unpacks the release to a
; temporary folder and runs that release's install.ps1 - so there is one install
; to reason about: %LOCALAPPDATA%\Programs\QResGUI, the Start menu shortcut, and
; the Settings > Apps entry whose uninstaller takes QRes's hooks out first. Setup
; itself isn't registered as an uninstaller for that reason.
;
; Built by package.ps1 -Installer once the release folder is staged:
;   ISCC /DAppVersion=1.9.0 /DStage=..\release\QResGUI-1.9.0-win64 installer\QResGUI.iss
;
; Exit codes, for winget's manifest: 0 installed; 2 QRes GUI or a game started
; through it is running; 1 anything else.

#ifndef AppVersion
  #error Pass /DAppVersion=<x.y.z>
#endif
#ifndef Stage
  #define Stage "..\release\QResGUI-" + AppVersion + "-win64"
#endif

[Setup]
AppId=QResGUI
AppName=QRes GUI
AppVersion={#AppVersion}
AppVerName=QRes GUI {#AppVersion}
AppPublisher=TheRealestNwah
AppPublisherURL=https://github.com/TheRealestNwah/qres-gui
AppSupportURL=https://github.com/TheRealestNwah/qres-gui/blob/main/docs/TROUBLESHOOTING.md
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
CreateAppDir=no
Uninstallable=no
DisableWelcomePage=no
DisableReadyPage=no
OutputDir=..\release
OutputBaseFilename=QResGUI-{#AppVersion}-setup
SetupIconFile=..\build\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
MinVersion=10.0

[Messages]
WelcomeLabel2=This installs QRes GUI {#AppVersion} for your Windows account, in %LOCALAPPDATA%\Programs\QResGUI.%n%nIt updates an earlier version in place: your game profiles, settings, Steam launch options and Playnite scripts stay as they are.
ReadyLabel2a=Setup is ready to install QRes GUI. Close QRes GUI first if it's open.

[Files]
Source: "{#Stage}\*"; DestDir: "{tmp}\QResGUI"; Flags: recursesubdirs createallsubdirs ignoreversion deleteafterinstall

[Run]
Filename: "{localappdata}\Programs\QResGUI\QResGUI.exe"; Description: "Open QRes GUI"; Flags: postinstall nowait skipifsilent; Check: Installed

[Code]
var
  InstallResult: Integer;

function Installed: Boolean;
begin
  Result := InstallResult = 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Log, Command: String;
  Output: AnsiString;
begin
  if CurStep <> ssPostInstall then
    exit;
  WizardForm.StatusLabel.Caption := 'Installing QRes GUI...';
  Log := ExpandConstant('{tmp}\install.log');
  Command := '/S /C ""' + ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe') +
    '" -NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\QResGUI\install.ps1') +
    '" > "' + Log + '" 2>&1"';
  if not Exec(ExpandConstant('{cmd}'), Command, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := 1;
  InstallResult := ResultCode;
  if InstallResult <> 0 then
  begin
    if not LoadStringFromFile(Log, Output) then
      Output := '';
    SuppressibleMsgBox('QRes GUI could not be installed.' + #13#10#13#10 + String(Output), mbError, MB_OK, IDOK);
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := InstallResult;
end;

#define AppVersion GetEnv("DGC_APP_VERSION")
#define PackageRoot GetEnv("DGC_PACKAGE_ROOT")
#define OutputDir GetEnv("DGC_OUTPUT_DIR")
#define OutputBaseFilename GetEnv("DGC_OUTPUT_BASE_FILENAME")
#define AppIcon GetEnv("DGC_APP_ICON")
#define WebView2Installer GetEnv("DGC_WEBVIEW2_INSTALLER")

[Setup]
AppId={{7A5CF9E1-B27E-4BC2-B723-D5AB6C7AF204}
AppName=Drug Gradient Chip
AppVersion={#AppVersion}
AppPublisher=Drug Gradient Chip
DefaultDirName={localappdata}\Programs\DrugGradientChip
DefaultGroupName=Drug Gradient Chip
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#AppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
PrivilegesRequired=lowest
UninstallDisplayName=Drug Gradient Chip

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#PackageRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Installer}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: deleteafterinstall

[Icons]
Name: "{group}\Drug Gradient Chip"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\resources\drug-gradient-chip.ico"
Name: "{group}\Drug Gradient Chip - Browser Mode"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher.pyw"" --browser-mode"; WorkingDir: "{app}"; IconFilename: "{app}\resources\drug-gradient-chip.ico"
Name: "{group}\Stop Drug Gradient Chip"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\stopper.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\resources\drug-gradient-chip.ico"
Name: "{autodesktop}\Drug Gradient Chip"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\resources\drug-gradient-chip.ico"; Tasks: desktopicon

[UninstallRun]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\stopper.pyw"" --quiet"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "StopDrugGradientChip"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.runtime"
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\runtime"
Type: dirifempty; Name: "{app}"

[Code]
function WebView2RuntimeVersion(): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Value) then
  begin
    Result := Value;
    exit;
  end;
  if RegQueryStringValue(HKLM, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Value) then
  begin
    Result := Value;
    exit;
  end;
  if RegQueryStringValue(HKLM, 'Software\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Value) then
  begin
    Result := Value;
    exit;
  end;
end;

procedure EnsureWebView2Runtime();
var
  ResultCode: Integer;
  InstallerPath: String;
  Version: String;
begin
  Version := WebView2RuntimeVersion();
  if Version <> '' then
  begin
    Log('WebView2 Runtime already installed: ' + Version);
    exit;
  end;

  WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime...';
  InstallerPath := ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
  if not FileExists(InstallerPath) then
  begin
    MsgBox('Microsoft Edge WebView2 Runtime installer is missing from this Setup package.', mbError, MB_OK);
    Abort;
  end;
  Log('WebView2 Runtime missing; running bundled Evergreen Standalone Installer.');
  if (not Exec(InstallerPath, '/silent /install', ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
     (ResultCode <> 0) then
  begin
    MsgBox('Microsoft Edge WebView2 Runtime installation failed. Browser Mode may still be used for troubleshooting if a browser is available.', mbError, MB_OK);
    Abort;
  end;
  Version := WebView2RuntimeVersion();
  if Version = '' then
  begin
    MsgBox('Microsoft Edge WebView2 Runtime could not be verified after installation.', mbError, MB_OK);
    Abort;
  end;
  Log('WebView2 Runtime installed: ' + Version);
end;

procedure StopExistingApplication();
var
  ResultCode: Integer;
  PythonPath: String;
  StopperPath: String;
begin
  PythonPath := ExpandConstant('{app}\runtime\pythonw.exe');
  StopperPath := ExpandConstant('{app}\stopper.pyw');
  if FileExists(PythonPath) and FileExists(StopperPath) then
  begin
    WizardForm.StatusLabel.Caption := 'Stopping existing Drug Gradient Chip instance...';
    Log('Stopping existing Drug Gradient Chip instance before upgrade.');
    if (not Exec(PythonPath, '"' + StopperPath + '" --quiet', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
       (ResultCode <> 0) then
    begin
      MsgBox('Could not stop the existing Drug Gradient Chip instance. Please close the app and retry setup.', mbError, MB_OK);
      Abort;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PowerShellPath: String;
  Parameters: String;
  LogsPath: String;
begin
  if CurStep = ssInstall then
  begin
    StopExistingApplication();
  end;

  if CurStep = ssPostInstall then
  begin
    EnsureWebView2Runtime();
    WizardForm.StatusLabel.Caption := 'Initializing local runtime. This may take several minutes...';
    PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    LogsPath := ExpandConstant('{app}\.runtime\logs');
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\scripts\initialize_installed_runtime.ps1') +
      '" -RuntimeRelocationTimeoutSeconds 600';
    if (not Exec(PowerShellPath, Parameters, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
       (ResultCode <> 0) then
    begin
      MsgBox('Local runtime initialization failed. See logs under:' + #13#10 + LogsPath, mbError, MB_OK);
      Abort;
    end;
  end;
end;

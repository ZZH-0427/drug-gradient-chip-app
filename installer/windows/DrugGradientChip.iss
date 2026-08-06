#define AppVersion GetEnv("DGC_APP_VERSION")
#define PackageRoot GetEnv("DGC_PACKAGE_ROOT")
#define OutputDir GetEnv("DGC_OUTPUT_DIR")
#define OutputBaseFilename GetEnv("DGC_OUTPUT_BASE_FILENAME")
#define AppIcon GetEnv("DGC_APP_ICON")

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

[Icons]
Name: "{group}\Drug Gradient Chip"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\resources\drug-gradient-chip.ico"
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
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PowerShellPath: String;
  Parameters: String;
  LogsPath: String;
begin
  if CurStep = ssPostInstall then
  begin
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

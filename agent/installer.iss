#define MyAppName "RedLine GS Agent"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "RedLine GS"
#define MyAppExeName "redline_agent.exe"

[Setup]
AppId={{B4E2F1A3-7C8D-4E5F-9A0B-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\RedLineGS
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=RedLineGS_setup
SetupIconFile=redlinegs.ico
InfoBeforeFile=info_before.txt
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; Silencia la ventana del agente al iniciarse
WindowVisible=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.bmp"; Flags: dontcopy
Source: "config.default.json"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

[Registry]
; Agregar al inicio de Windows (HKCU — sin admin, Inno lo elimina al desinstalar)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "RedLine GS Agent"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Run]
; Iniciar el agente automaticamente — abre el login de Nextcloud si no hay sesion
Filename: "{app}\{#MyAppExeName}"; Flags: nowait

[Code]
procedure InitializeWizard;
var
  LogoImg: TBitmapImage;
  LogoH: Integer;
begin
  ExtractTemporaryFile('logo.bmp');

  LogoH := 50;

  // Reducir el memo para dejar espacio al logo en la parte inferior
  WizardForm.InfoBeforeMemo.Height := WizardForm.InfoBeforeMemo.Height - LogoH - 8;

  LogoImg := TBitmapImage.Create(WizardForm.InfoBeforePage);
  LogoImg.Parent := WizardForm.InfoBeforePage;
  LogoImg.Bitmap.LoadFromFile(ExpandConstant('{tmp}\logo.bmp'));
  LogoImg.AutoSize := False;
  LogoImg.Stretch := True;
  LogoImg.Width := 156;
  LogoImg.Height := LogoH;
  LogoImg.Left := (WizardForm.InfoBeforePage.Width - LogoImg.Width) div 2;
  LogoImg.Top := WizardForm.InfoBeforeMemo.Top + WizardForm.InfoBeforeMemo.Height + 4;
end;

function IsLoggedIn: Boolean;
var
  ConfigPath: String;
  ConfigContent: AnsiString;
begin
  Result := False;
  ConfigPath := ExpandConstant('{userappdata}\RedLineGS\config.json');
  if FileExists(ConfigPath) then begin
    if LoadStringFromFile(ConfigPath, ConfigContent) then
      Result := Pos('"jwt_token": "ey', ConfigContent) > 0;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption :=
      'Completa el login con Nextcloud en el navegador que se abrió.' + #13#10 +
      'Una vez iniciada la sesión podrás hacer clic en Finalizar.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if CurPageID = wpFinished then begin
    if not IsLoggedIn then begin
      MsgBox('Aún no se ha completado el login en SKY.' + #13#10 +
             'Por favor inicia sesión en el navegador y vuelve a intentarlo.',
             mbInformation, MB_OK);
      Result := False;
    end else
      ShellExec('open', 'https://sky.redlinegs.com/apps/external/1/', '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Limpiar clave de autostart que dejaron versiones anteriores (via --install)
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RedLine GS Agent');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // Detener el agente silenciosamente antes de reemplazar archivos
  ShellExec('', 'taskkill', '/F /IM redline_agent.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigContent: AnsiString;
  AppDataDir: String;
  ConfigDst: String;
begin
  if CurStep = ssPostInstall then begin
    AppDataDir := ExpandConstant('{userappdata}\RedLineGS');
    ConfigDst := AppDataDir + '\config.json';

    // Solo escribir el config por defecto si no existe uno previo con tokens
    if not FileExists(ConfigDst) then begin
      ExtractTemporaryFile('config.default.json');
      if LoadStringFromFile(ExpandConstant('{tmp}\config.default.json'), ConfigContent) then begin
        ForceDirectories(AppDataDir);
        SaveStringToFile(ConfigDst, ConfigContent, False);
      end;
    end;
  end;
end;

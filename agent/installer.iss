#define MyAppName "RedLine GS Agent"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "RedLine GS"
#define MyAppExeName "redline_agent.exe"

[Setup]
AppId={{B4E2F1A3-7C8D-4E5F-9A0B-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Instalación per-usuario: sin UAC, sin permisos de administrador.
; Soporta despliegue silencioso por IT: RedLineGS_setup.exe /VERYSILENT /SUPPRESSMSGBOXES
DefaultDirName={localappdata}\RedLineGS
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=dist
OutputBaseFilename=RedLineGS_setup
SetupIconFile=redlinegs.ico
InfoBeforeFile=info_before.txt
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.bmp"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

[Registry]
; Agregar al inicio de Windows (HKCU — sin admin, Inno lo elimina al desinstalar)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "RedLine GS Agent"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Run]
; Iniciar el agente automaticamente — queda a la espera de emparejamiento desde Skylog
Filename: "{app}\{#MyAppExeName}"; Flags: nowait

[UninstallRun]
; Detener el agente antes de borrar archivos (per-usuario, no requiere admin)
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillAgent"

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

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption :=
      'Agente instalado.' + #13#10 +
      'Abre Skylog en tu navegador: el agente se vinculara' + #13#10 +
      'automaticamente con tu cuenta.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if CurPageID = wpFinished then
    ShellExec('open', 'https://sky.redlinegs.com/apps/external/1/', '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Limpiar clave de autostart que dejaron versiones anteriores (via --install)
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RedLine GS Agent');
end;

// Busca el desinstalador de una version previa (mismo AppId, sufijo _is1 de Inno)
function GetUninstallString(Root: Integer): String;
var
  UnInstPath: String;
  UnInstallString: String;
begin
  UnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B4E2F1A3-7C8D-4E5F-9A0B-1D2E3F4A5B6C}_is1';
  UnInstallString := '';
  RegQueryStringValue(Root, UnInstPath, 'UninstallString', UnInstallString);
  Result := UnInstallString;
end;

// True si redline_agent.exe sigue corriendo (tasklist + find devuelve 0 si lo encuentra)
function AgentStillRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'),
    '/C tasklist /FI "IMAGENAME eq redline_agent.exe" | find /I "redline_agent.exe" >nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  UninstStr: String;
begin
  Result := '';

  // 1. Detener el agente silenciosamente (corre como el mismo usuario, no requiere admin)
  ShellExec('', 'taskkill', '/F /IM redline_agent.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // 1b. Las versiones 1.x arrancaban ELEVADAS (el instalador viejo era admin), asi
  // que el taskkill normal no puede matarlas. Si el proceso sigue vivo, reintentar
  // con elevacion — un aviso UAC solo durante la migracion. Sin esto, el agente
  // viejo queda corriendo, ocupa el puerto 7337 y sigue reportando su version vieja.
  if AgentStillRunning() then begin
    ShellExec('runas', 'taskkill', '/F /IM redline_agent.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
  end;

  // 2. Desinstalar una version per-usuario previa (HKCU): silencioso, sin UAC
  UninstStr := GetUninstallString(HKCU);
  if UninstStr <> '' then begin
    UninstStr := RemoveQuotes(UninstStr);
    Exec(UninstStr, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    // El desinstalador (unins000.exe) se auto-elimina de forma asincrona; darle un momento
    Sleep(1500);
  end;

  // 3. Version vieja de sistema (v1.x en Program Files, HKLM): intentar desinstalar
  // con elevacion — un unico aviso UAC solo durante la migracion. Si el usuario
  // cancela, seguimos igual: el proceso ya fue detenido y la clave de autostart
  // se sobreescribe con la nueva ruta, asi que la version vieja no vuelve a correr.
  UninstStr := GetUninstallString(HKLM);
  if UninstStr <> '' then begin
    UninstStr := RemoveQuotes(UninstStr);
    ShellExec('runas', UninstStr, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1500);
  end;
end;

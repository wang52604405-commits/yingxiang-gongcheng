; 工程影像管理平台 安装脚本（Inno Setup 6）
; 编译：ISCC.exe 安装脚本.iss

[Setup]
AppId={{8E7C6C39-8E2F-4B4E-9B1A-9F8D3C4E5A6B}
AppName=工程影像管理平台
AppVersion=A20260909-2.90
AppVerName=工程影像管理平台 A20260909-2.90
AppPublisher=工程影像管理平台
DefaultDirName={localappdata}\工程影像管理平台
DefaultGroupName=工程影像管理平台
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=客户可发送安装包-Win10\发给客户
OutputBaseFilename=安装程序
SetupIconFile=assets\app_icon.ico
UninstallDisplayIcon={app}\工程影像管理平台.exe
UninstallDisplayName=工程影像管理平台
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; PrepareToInstall 会按“目标安装目录 + 固定程序名”精确关闭本应用。
; 禁用 Restart Manager 的宽泛关闭，避免影响其它目录里的同名程序。
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "chs"; MessagesFile: "assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机自动启动本地服务入口"; GroupDescription: "附加任务:"

[Files]
; onedir 程序目录整体安装（启动无需解压，速度快）
Source: "dist\工程影像管理平台\*"; DestDir: "{app}"; Excludes: "trial.json,license.dat,cloud_account.json,cloud_config.json,product_config_cache.json,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\工程影像管理平台"; Filename: "{app}\工程影像管理平台.exe"; IconFilename: "{app}\app_icon.ico"; WorkingDir: "{app}"
Name: "{autodesktop}\工程影像管理平台"; Filename: "{app}\工程影像管理平台.exe"; IconFilename: "{app}\app_icon.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "Version"; ValueData: "A20260909-2.90"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "工程影像管理平台"; ValueData: """{app}\工程影像管理平台.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; 普通安装显示一个可选启动项；静默自动更新无交互启动。两条互斥，任何模式都只启动一次。
Filename: "{app}\工程影像管理平台.exe"; Description: "启动 工程影像管理平台"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\工程影像管理平台.exe"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: files; Name: "{app}\trial.json"
Type: files; Name: "{app}\server.out.log"
Type: files; Name: "{app}\server.err.log"
Type: files; Name: "{app}\license.dat"
Type: files; Name: "{app}\*.log"
Type: dirifempty; Name: "{app}"

[Code]
var
  CachedDataDir: String;

function SetEnvironmentVariable(lpName, lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function NormalizeDirectory(Value: String): String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Value));
end;

function GetDataDir(Param: String): String;
var
  ExistingDataDir: String;
begin
  { 升级安装保留原数据目录；首次安装使用当前 Windows 用户独立目录。 }
  if CachedDataDir <> '' then
    Result := CachedDataDir
  else if RegQueryStringValue(HKCU, 'Software\工程影像管理平台', 'DataDir', ExistingDataDir) and
     (ExistingDataDir <> '') then
    Result := ExistingDataDir
  else
    Result := ExpandConstant('{localappdata}\工程影像管理平台\data');
end;

{ 只关闭目标安装目录里的两个本应用进程。若 5088 被其它程序占用，拒绝继续，绝不误杀。 }
function StopInstalledAppProcesses(OldInstallDir: String): String;
var
  PS: String;
  ExitCode: Integer;
begin
  Result := '';
  SetEnvironmentVariable('ALBUM_UPDATE_INSTALL_DIR', ExpandConstant('{app}'));
  SetEnvironmentVariable('ALBUM_UPDATE_OLD_DIR', OldInstallDir);
  PS := '$ErrorActionPreference=''Stop'';' +
    '$target=[IO.Path]::GetFullPath($env:ALBUM_UPDATE_INSTALL_DIR).TrimEnd([char[]]''\/'');' +
    '$targets=@($target);if($env:ALBUM_UPDATE_OLD_DIR){$targets+=[IO.Path]::GetFullPath($env:ALBUM_UPDATE_OLD_DIR).TrimEnd([char[]]''\/'')};' +
    '$allowed=@(''album_server.exe'',''工程影像管理平台.exe'');' +
    'function IsOurs($p){try{$x=[string]$p.ExecutablePath;if(-not $x){return $false};' +
    '$full=[IO.Path]::GetFullPath($x);$name=[IO.Path]::GetFileName($full);' +
    '$dir=[IO.Path]::GetDirectoryName($full).TrimEnd([char[]]''\/'');' +
    'return (($allowed -contains $name) -and @($targets|Where-Object{[string]::Equals($_,$dir,[StringComparison]::OrdinalIgnoreCase)}).Count -gt 0)}catch{return $false}};' +
    '$ours=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{IsOurs $_});' +
    '$ours|ForEach-Object{Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue};' +
    'Start-Sleep -Milliseconds 500;' +
    'if(@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{IsOurs $_}).Count -ne 0){exit 24};' +
    '$listenerPids=@(Get-NetTCPConnection -LocalPort 5088 -State Listen -ErrorAction SilentlyContinue|ForEach-Object{$_.OwningProcess}|Sort-Object -Unique);' +
    'foreach($listenerPid in $listenerPids){$owner=Get-CimInstance Win32_Process -Filter (''ProcessId='' + [int]$listenerPid) -ErrorAction SilentlyContinue;' +
    'if(-not $owner -or -not (IsOurs $owner)){exit 23}};' +
    '$listenerPids|ForEach-Object{Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue};exit 0';
  if not Exec('powershell.exe', '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + PS + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    ExitCode := 25;
  SetEnvironmentVariable('ALBUM_UPDATE_INSTALL_DIR', '');
  SetEnvironmentVariable('ALBUM_UPDATE_OLD_DIR', '');
  if ExitCode = 23 then
    Result := '端口 5088 正被其它程序占用。为避免误关程序，安装已停止，请先关闭占用程序后重试。'
  else if ExitCode = 24 then
    Result := '旧版本未能安全退出，请关闭工程影像管理平台后重试。'
  else if ExitCode <> 0 then
    Result := '无法安全检查旧版本进程，安装已停止。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(GetDataDir(''));
    { 清除 A2.0 Python 安装器遗留的第二个卸载入口。该脚本允许删除 DataDir，
      新版安装成功后只保留 Inno 自己的安全卸载入口。 }
    RegDeleteKeyIncludingSubkeys(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\工程影像管理平台'
    );
    DeleteFile(ExpandConstant('{app}\卸载工程影像管理平台.ps1'));
  end;
end;

{ 在安装(更新)开始前释放端口，避免 Inno 检测到文件被占用而中止/失败。 }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldDir: String;
  OldUnins: String;
  UninsCode: Integer;
begin
  { 必须在旧卸载器删除注册表键之前缓存自定义资料目录。 }
  if CachedDataDir = '' then
    RegQueryStringValue(HKCU, 'Software\工程影像管理平台', 'DataDir', CachedDataDir);
  OldDir := '';
  RegQueryStringValue(HKCU, 'Software\工程影像管理平台', 'InstallDir', OldDir);

  { 精确关闭目标目录及注册表记录的旧目录内进程；遇到其它程序占用端口则停止安装。 }
  Result := StopInstalledAppProcesses(OldDir);
  if Result <> '' then
    exit;

  { 大版本升级：先静默卸载旧版，再装新版，确保不残留旧启动器/旧依赖文件。
    数据目录(DataDir)位于程序目录之外，自始至终独立，Inno 卸载不会删除，用户数据安全保留。
    只有当旧版确实存在(注册表 InstallDir 指向的 unins000.exe 可执行)时才卸载。 }
  if (OldDir <> '') and
     (CompareText(NormalizeDirectory(OldDir), NormalizeDirectory(ExpandConstant('{app}'))) <> 0) then
  begin
    OldUnins := OldDir + '\unins000.exe';
    if FileExists(OldUnins) then
    begin
      { 从旧目录直接运行卸载程序，静默且不删数据。注意不能运行当前程序目录下的卸载器。 }
      ShellExec('open', OldUnins, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', OldDir, SW_HIDE, ewWaitUntilTerminated, UninsCode);
      { 等待卸载完成后安装程序继续；卸载器会自行删除旧目录(含旧 exe)，不影响位于临时/当前目录的新安装器。 }
      Sleep(2000);
    end;
  end;
  Result := '';
end;


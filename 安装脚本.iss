; 工程影像管理平台 安装脚本（Inno Setup 6）
; 编译：ISCC.exe 安装脚本.iss

[Setup]
AppId={{8E7C6C39-8E2F-4B4E-9B1A-9F8D3C4E5A6B}
AppName=工程影像管理平台
AppVersion=A20260822-2.64
AppVerName=工程影像管理平台 A20260822-2.64
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
; 更新或安装时强制关闭正在运行的桌面启动器和后台服务，避免旧文件被保留导致版本未更新。
CloseApplications=force
CloseApplicationsFilter=工程影像管理平台.exe,album_server.exe
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
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "Version"; ValueData: "A20260822-2.64"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "工程影像管理平台"; ValueData: """{app}\工程影像管理平台.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\工程影像管理平台.exe"; Description: "启动 工程影像管理平台"; WorkingDir: "{app}"; Flags: nowait postinstall

[UninstallDelete]
Type: files; Name: "{app}\trial.json"
Type: files; Name: "{app}\server.out.log"
Type: files; Name: "{app}\server.err.log"
Type: files; Name: "{app}\license.dat"
Type: files; Name: "{app}\*.log"
Type: dirifempty; Name: "{app}"

[Code]
function GetDataDir(Param: String): String;
var
  ExistingDataDir: String;
begin
  { 升级安装保留原数据目录；首次安装使用当前 Windows 用户独立目录。 }
  if RegQueryStringValue(HKCU, 'Software\工程影像管理平台', 'DataDir', ExistingDataDir) and
     (ExistingDataDir <> '') then
    Result := ExistingDataDir
  else
    Result := ExpandConstant('{localappdata}\工程影像管理平台\data');
end;

{ 释放应用独占端口：杀掉监听 5088 的本应用进程(打包版 album_server.exe / 开发版 python.exe)。
  CloseApplications 对无窗口后台服务(album_server.exe 用 CREATE_NO_WINDOW 启动)不可靠，
  这里在安装/更新前主动确定性地释放端口，否则更新会因端口占用覆盖失败。 }
procedure ReleaseServerPort;
var
  PS: String;
begin
  PS := 'Get-NetTCPConnection -LocalPort 5088 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess } | Where-Object { $_ -and $_ -ne $PID } | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }';
  Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PS + '"', '', SW_HIDE, ewWaitUntilTerminated, Result);
  { 兜底：结束本应用的打包版服务进程（不误杀其它 python）。 }
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM album_server.exe /T /F 2>nul', '', SW_HIDE, ewNoWait, Result);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ForceDirectories(GetDataDir(''));
end;

{ 在安装(更新)开始前释放端口，避免 Inno 检测到文件被占用而中止/失败。 }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  ReleaseServerPort;
  Result := '';
end;


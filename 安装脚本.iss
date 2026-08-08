; 工程影像管理平台 安装脚本（Inno Setup 6）
; 编译：ISCC.exe 安装脚本.iss

[Setup]
AppId={{8E7C6C39-8E2F-4B4E-9B1A-9F8D3C4E5A6B}
AppName=工程影像管理平台
AppVersion=A20260809-2.28
AppVerName=工程影像管理平台 A20260809-2.28
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
CloseApplications=yes
CloseApplicationsFilter=工程影像管理平台.exe,album_server.exe
SetupLogging=yes

[Languages]
Name: "chs"; MessagesFile: "assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机自动启动本地服务入口"; GroupDescription: "附加任务:"

[Files]
; onedir 程序目录整体安装（启动无需解压，速度快）
Source: "dist\工程影像管理平台\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\工程影像管理平台"; Filename: "{app}\工程影像管理平台.exe"; IconFilename: "{app}\app_icon.ico"; WorkingDir: "{app}"
Name: "{autodesktop}\工程影像管理平台"; Filename: "{app}\工程影像管理平台.exe"; IconFilename: "{app}\app_icon.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\工程影像管理平台"; ValueType: string; ValueName: "Version"; ValueData: "A20260809-2.28"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "工程影像管理平台"; ValueData: """{app}\工程影像管理平台.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\工程影像管理平台.exe"; Description: "启动 工程影像管理平台"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\trial.json"
Type: files; Name: "{app}\server.out.log"
Type: files; Name: "{app}\server.err.log"
Type: files; Name: "{app}\license.dat"
Type: files; Name: "{app}\*.log"
Type: dirifempty; Name: "{app}"

[Code]
function GetDataDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\工程影像资料'
  else
    Result := 'C:\工程影像资料';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ForceDirectories(GetDataDir(''));
end;

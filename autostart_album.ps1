$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 5088

# 旧源码自启动只保留给显式开发环境。正式安装版已有独立 Windows 开机自启动入口，
# 默认禁止 python run.py 抢占生产 5088，避免与 album_server.exe 冲突。
$AllowSourceAutostart = [string]$env:ALBUM_ENABLE_SOURCE_AUTOSTART
if ($AllowSourceAutostart -notmatch '^(?i:1|true|yes)$') {
    exit 0
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    exit 1
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    exit 0
}

$env:ALBUM_HOST = "0.0.0.0"
$env:ALBUM_PORT = "$Port"
$env:ALBUM_DATA_DIR = "D:\工程影像资料"
New-Item -ItemType Directory -Path $env:ALBUM_DATA_DIR -Force | Out-Null

Start-Process `
    -FilePath $Python.Source `
    -ArgumentList "run.py" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$ProjectDir\server.out.log" `
    -RedirectStandardError "$ProjectDir\server.err.log"

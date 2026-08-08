@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "ALBUM_HOST=0.0.0.0"
set "ALBUM_PORT=5088"
set "ALBUM_DATA_DIR=D:\工程影像资料"

if not exist "%ALBUM_DATA_DIR%" mkdir "%ALBUM_DATA_DIR%"

where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python。请先安装 Python 3.9 或更高版本，并勾选 Add python.exe to PATH。
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import flask, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo 正在安装运行依赖，请稍等...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败。请检查网络后重新运行本文件。
    pause
    exit /b 1
  )
)

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%ALBUM_PORT%/setup'"

echo.
echo 工程影像管理平台已启动。
echo 本机配置页：http://127.0.0.1:%ALBUM_PORT%/setup
echo 局域网登录网址会在下方显示。其他电脑需连接同一个局域网。
echo 若其他电脑无法打开，请在 Windows 防火墙中允许 TCP %ALBUM_PORT% 端口。
echo.
python run.py
pause

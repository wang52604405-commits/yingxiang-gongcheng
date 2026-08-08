@echo off
setlocal
cd /d "%~dp0"
python build_all.py
if errorlevel 1 (
    echo.
    echo [BUILD FAILED] see errors above.
    pause
    exit /b 1
)
pause

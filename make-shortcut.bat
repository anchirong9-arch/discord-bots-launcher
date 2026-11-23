@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"
title Create Desktop Shortcut
color 0B

echo ==========================================================
echo    Create Desktop Shortcut
echo ==========================================================
echo.

if not exist "launcher.py" goto no_files
if not exist "assets\app.ico" goto no_icon
if not exist ".venv\Scripts\pythonw.exe" goto no_venv

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1"
if errorlevel 1 goto ps_fail
echo.
pause
exit /b 0

:no_files
echo [ERROR] launcher.py not found.
pause
exit /b 1

:no_icon
echo [ERROR] assets\app.ico not found. Download the ZIP again.
pause
exit /b 1

:no_venv
echo [NOTE] Run run.bat once first.
pause
exit /b 1

:ps_fail
echo.
echo [ERROR] Could not create the shortcut.
pause
exit /b 1

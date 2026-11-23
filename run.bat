@echo off
rem English-named launcher, same as 실행하기.bat
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"
title BaekSutalk Discord Bots
color 0B

echo ==========================================================
echo    BaekSutalk Discord Bots - log bot / music bot
echo ==========================================================
echo.

if not exist "launcher.py" goto no_files

set "PYEXE="
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto try_python
set "PYEXE=py -3"
goto python_ready

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
set "PYEXE=python"

:python_ready
%PYEXE% -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if errorlevel 1 goto old_python

if exist ".venv\Scripts\python.exe" goto have_venv
echo [1/3] First run only. This takes 1-3 minutes.
echo       Creating the virtual environment...
%PYEXE% -m venv ".venv"
if errorlevel 1 goto venv_fail
goto check_pkg

:have_venv
echo [1/3] Found the prepared environment.

:check_pkg
".venv\Scripts\python.exe" -c "import discord, dotenv, yt_dlp, nacl, imageio_ffmpeg" >nul 2>nul
if not errorlevel 1 goto run_launcher

echo [2/3] Installing bot packages. First time takes 1-3 minutes.
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check -q
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto pip_warn
goto run_launcher

:pip_warn
echo.
echo [NOTE] Package install did not finish. Check your internet connection.
echo.

:run_launcher
echo [3/3] Checking updates, starting the bots, opening the status page.
echo.
if not exist ".venv\Scripts\pythonw.exe" goto run_console
start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.py"
timeout /t 2 >nul
echo    * No console window stays open. Bots run in the background.
echo    * Status page: http://127.0.0.1:8771
echo    * Stop: stop.bat  /  Logs: logs folder
echo.
echo You can close this window. The bots keep running.
timeout /t 3 >nul
exit /b 0

:run_console
echo    (pythonw not found - running in this window)
".venv\Scripts\python.exe" launcher.py
goto end

:no_files
echo [ERROR] launcher.py not found. Run this from the unzipped folder.
echo.
pause
goto end

:no_python
echo.
echo [ERROR] Python is not installed.
echo   1) Open https://www.python.org/downloads/windows/
echo   2) Install Python 3.12
echo   3) Check Add python.exe to PATH during setup
echo.
pause
goto end

:old_python
echo.
echo [ERROR] Python 3.9 or newer is required.
echo.
pause
goto end

:venv_fail
echo.
echo [ERROR] Could not create .venv. Try unzipping to a simple path like C:\discord-bots-launcher
echo.
pause
goto end

:end
echo.
echo Launcher stopped. You can close this window.
pause >nul
exit /b 0

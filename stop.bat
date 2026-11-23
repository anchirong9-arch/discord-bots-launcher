@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"
title Stop Discord Bots
color 0C

echo ==========================================================
echo    Stop Discord Bots
echo ==========================================================
echo.

set "PYRUN="
if exist ".venv\Scripts\python.exe" set "PYRUN=.venv\Scripts\python.exe"
if not defined PYRUN goto try_py
goto do_stop

:try_py
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto try_python
set "PYRUN=py -3"
goto do_stop

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
set "PYRUN=python"

:do_stop
if not exist "launcher.py" goto no_files
%PYRUN% launcher.py --stop
echo.
pause
exit /b 0

:no_files
echo [ERROR] launcher.py not found. Run this from the unzipped folder.
pause
exit /b 1

:no_python
echo [ERROR] Python not found. End the python process in Task Manager.
pause
exit /b 1

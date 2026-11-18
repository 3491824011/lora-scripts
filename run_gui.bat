@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "HF_HOME=%~dp0huggingface"

if exist "%~dp0python\python.exe" (
    set "PYTHONHOME=%~dp0python"
    set "PYTHONPATH="
    set "PYTHONSAFEPATH="
    set "PATH=%~dp0python;%~dp0python\Scripts;%PATH%"
    "%~dp0python\python.exe" -s gui.py %*
    goto :finished
)

if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" gui.py %*
    goto :finished
)

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" gui.py %*
    goto :finished
)

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Run scripts\install.ps1 or scripts\install-cn.ps1 first.
    pause
    exit /b 1
)

python gui.py %*

:finished
set "GUI_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %GUI_EXIT_CODE%

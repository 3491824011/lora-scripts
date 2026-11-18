@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "HF_HOME=%~dp0huggingface"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "%~dp0python\python.exe" (
    set "PYTHONHOME=%~dp0python"
    set "PYTHONPATH="
    set "PYTHONSAFEPATH="
    set "PATH=%~dp0python;%~dp0python\Scripts;%PATH%"
    set "PYTHON_EXE=%~dp0python\python.exe"
    set "PYTHON_ARGS=-s"
    goto :check_environment
)

if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
    goto :check_environment
)

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
    goto :check_environment
)

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Run scripts\setup-windows.bat first. It downloads Python 3.11 and the dependencies.
    pause
    exit /b 1
)
set "PYTHON_EXE=python"

:check_environment
"%PYTHON_EXE%" -c "import torch" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] PyTorch is not installed for the selected Python.
    echo Run scripts\setup-windows.bat first. It downloads Python 3.11 and the dependencies.
    echo Selected Python: %PYTHON_EXE%
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 2)" >nul 2>nul
if errorlevel 2 (
    echo.
    echo [WARN] CUDA-enabled PyTorch was not detected.
    echo If this computer has an NVIDIA GPU, run scripts\setup-windows.bat to install the CUDA build.
    echo Selected Python: %PYTHON_EXE%
    echo.
)

"%PYTHON_EXE%" %PYTHON_ARGS% gui.py %*

:finished
set "GUI_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %GUI_EXIT_CODE%

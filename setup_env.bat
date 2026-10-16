@echo off
rem setup_env.bat - creates a Python virtual environment for SLDS project 1.3.
rem Double-click it, or run it from Command Prompt, inside the "group project" folder.
rem Safe to run again: it reuses .venv and only installs or updates packages.

cd /d "%~dp0"

rem 1. Find Python (the "py" launcher first, then "python")
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation, then run this file again.
    pause
    exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or newer is needed. Found:
    %PY% --version
    echo Install Python 3.12 from https://www.python.org/downloads/ and run this file again.
    pause
    exit /b 1
)
echo Using:
%PY% --version

rem 2. Create the virtual environment in .venv (once)
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Could not create the virtual environment.
        pause
        exit /b 1
    )
)

rem 3. Install packages into it
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Package installation failed. Check your internet connection and run this file again.
    pause
    exit /b 1
)

rem 4. Make it available as a notebook kernel called "Python (SLDS 1.3)"
".venv\Scripts\python.exe" -m ipykernel install --user --name slds-1.3 --display-name "Python (SLDS 1.3)"

rem 5. Check
".venv\Scripts\python.exe" -c "import sys, polars, numpy, matplotlib; print('OK  Python', sys.version.split()[0], '| polars', polars.__version__, '| numpy', numpy.__version__, '| matplotlib', matplotlib.__version__)"
echo.
echo Done. In Jupyter or VS Code choose the kernel "Python (SLDS 1.3)".
echo To start Jupyter Lab from this folder:  .venv\Scripts\jupyter-lab.exe
pause

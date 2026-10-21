@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem Find Python 3.10+ in PATH, the py launcher, or common install folders.
set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    python3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=python3"
)
if not defined PY (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%~fD\python.exe" set "PY="%%~fD\python.exe""
    )
)
if not defined PY (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if exist "%%~fD\python.exe" set "PY="%%~fD\python.exe""
    )
)
if not defined PY (
    for /d %%D in ("C:\Program Files (x86)\Python3*") do (
        if exist "%%~fD\python.exe" set "PY="%%~fD\python.exe""
    )
)
if not defined PY (
    echo.
    echo Python 3.10+ was not found.
    echo Install it from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python 3.10+ is required. Found:
    %PY% --version
    echo Please install a newer Python from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo Using Python: %PY%
%PY% sender_server.py %*

echo.
echo Server stopped. Press any key to close this window.
pause >nul

@echo off
cd /d "%~dp0"

rem Find Python: try py launcher first (always in C:\Windows), then python, then python3
set PYTHON=
where py      >nul 2>&1 && set PYTHON=py
if "%PYTHON%"=="" where python  >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" where python3 >nul 2>&1 && set PYTHON=python3

if "%PYTHON%"=="" (
    echo.
    echo [ERROR] Python not found.
    echo Please install Python from https://www.python.org
    echo During installation, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo Python: %PYTHON%
echo Installing / checking packages...
%PYTHON% -m pip install -r requirements.txt -q --no-warn-script-location

echo Launching app...
%PYTHON% -m streamlit run app.py
pause
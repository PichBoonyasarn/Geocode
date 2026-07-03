@echo off
cd /d "%~dp0"

:: Find Python — py.exe launcher (C:\Windows\py.exe) is always present on Windows
:: regardless of PATH config. Fall back to python / python3 if absent.
set PYTHON=
where py      >nul 2>&1 && set PYTHON=py
if "%PYTHON%"=="" where python  >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" where python3 >nul 2>&1 && set PYTHON=python3

if "%PYTHON%"=="" (
    echo.
    echo [エラー] Pythonが見つかりません。
    echo https://www.python.org からインストールし、
    echo インストール時に "Add Python to PATH" を選択してください。
    echo.
    pause
    exit /b 1
)

echo Pythonコマンド: %PYTHON%
echo パッケージを確認中...
%PYTHON% -m pip install -r requirements.txt -q --no-warn-script-location

echo アプリを起動しています...
%PYTHON% -m streamlit run app.py
pause

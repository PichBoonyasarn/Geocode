@echo off
cd /d "%~dp0"

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Pythonがインストールされていません。
    echo https://www.python.org からインストールしてください。
    pause
    exit /b 1
)

:: Install / update packages silently on first run
echo パッケージを確認中...
python -m pip install -r requirements.txt -q

:: Launch the app
echo アプリを起動しています...
python -m streamlit run app.py
pause

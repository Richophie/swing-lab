@echo off
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required.
  pause
  exit /b
)
python -c "import flask,yfinance,pandas,numpy,requests" >nul 2>nul
if errorlevel 1 python -m pip install -r requirements.txt
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8766"
python app.py
pause

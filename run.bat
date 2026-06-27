@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=D:\Users\dingm\anaconda3\envs\finagent\python.exe"
if exist "%PY%" (
    "%PY%" main.py
) else (
    echo [run.bat] finagent python not found, falling back to PATH python ...
    python main.py
)
pause

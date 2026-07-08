@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=D:\Users\dingm\anaconda3\envs\finagent\python.exe"
if exist "%PY%" (
    "%PY%" main.py -c
) else (
    python main.py -c
)
pause

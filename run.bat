@echo off
REM 一键启动大类资产配置 agent（自动切到 finagent 环境）
REM 用法：双击本文件，或在命令行运行 run.bat
chcp 65001 >nul
cd /d "%~dp0"
call conda activate finagent 2>nul
if errorlevel 1 (
    echo [提示] conda activate 失败，改用环境内 python 直接运行...
    "D:\Users\dingm\anaconda3\envs\finagent\python.exe" main.py
) else (
    python main.py
)
pause

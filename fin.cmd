@echo off
chcp 65001 >nul
setlocal

set "ROOT=F:\vibecoding\agent_fin"
set "PY=D:\Users\dingm\anaconda3\envs\finagent\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "%ROOT%" || exit /b 1

if /i "%~1"=="setup" (
    "%PY%" main.py --setup-api
    exit /b %errorlevel%
)

if /i "%~1"=="claude" (
    "%PY%" main.py --use-claude-api
    exit /b %errorlevel%
)

if /i "%~1"=="deepseek" (
    "%PY%" main.py --use-deepseek-api
    exit /b %errorlevel%
)

if /i "%~1"=="test" (
    "%PY%" main.py --test-api
    exit /b %errorlevel%
)

if /i "%~1"=="resume" (
    "%PY%" main.py -c
    exit /b %errorlevel%
)

if /i "%~1"=="tools" (
    "%PY%" -c "import asyncio, main, trace_state; stats={'turns':0,'tokens':0,'context_compactions':0,'tool_errors':0,'trace':trace_state.AgentTrace(),'messages':[]}; asyncio.run(main.handle_local_command('/tools', stats))"
    exit /b %errorlevel%
)

if /i "%~1"=="menu" (
    call "%ROOT%\agent.bat"
    exit /b %errorlevel%
)

"%PY%" main.py %*
exit /b %errorlevel%

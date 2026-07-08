@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=D:\Users\dingm\anaconda3\envs\finagent\python.exe"
if not exist "%PY%" set "PY=python"

:menu
cls
echo ==================================================
echo   Financial Agent Launcher
echo ==================================================
echo   1. Start new session
echo   2. Setup or change API
echo   3. Test API connection
echo   4. Resume last session
echo   5. Show tool catalog
echo   0. Exit
echo.
choice /c 123450 /n /m "Choose: "

if errorlevel 6 goto end
if errorlevel 5 goto tools
if errorlevel 4 goto resume
if errorlevel 3 goto testapi
if errorlevel 2 goto setup
if errorlevel 1 goto start

:start
"%PY%" main.py
goto pause_menu

:setup
"%PY%" main.py --setup-api
goto pause_menu

:testapi
"%PY%" main.py --test-api
goto pause_menu

:resume
"%PY%" main.py -c
goto pause_menu

:tools
"%PY%" -c "import asyncio, main, trace_state; stats={'turns':0,'tokens':0,'context_compactions':0,'tool_errors':0,'trace':trace_state.AgentTrace(),'messages':[]}; asyncio.run(main.handle_local_command('/tools', stats))"
goto pause_menu

:pause_menu
echo.
pause
goto menu

:end
endlocal

@echo off
rem ============================================================
rem  MathTutor Launcher
rem  Starts the Streamlit app on port 8501 and opens the browser
rem ============================================================
setlocal
cd /d "%~dp0"

chcp 65001 >nul
title MathTutor Launcher

rem ---- 1. check if port 8501 is already in use -----------------
netstat -ano | findstr /R /C:":8501 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Port 8501 is already in use - MathTutor may be running.
    echo        Open http://localhost:8501 or run stop.bat first.
    pause
    exit /b 1
)

rem ---- 2. locate python (conda env "agent" preferred) ----------
set "PY=C:\Users\22094\.conda\envs\agent\python.exe"
if not exist "%PY%" set "PY=python"

rem ---- 3. environment -------------------------------------------
set "PYTHONPATH=%~dp0src"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"

echo.
echo  Starting MathTutor ...
echo    Python : %PY%
echo    App    : http://localhost:8501
echo.

rem ---- 4. launch streamlit in a new window ----------------------
start "MathTutor-streamlit" "%PY%" -m streamlit run "%~dp0src\frontend\app.py"

rem ---- 5. open browser after a short delay ----------------------
timeout /t 4 /nobreak >nul
start "" "http://localhost:8501"

endlocal

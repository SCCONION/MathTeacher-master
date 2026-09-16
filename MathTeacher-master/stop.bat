@echo off
rem ============================================================
rem  MathTutor Stopper
rem  Kills every process listening on port 8501
rem ============================================================
setlocal
cd /d "%~dp0"

chcp 65001 >nul
title MathTutor Stopper

echo Stopping MathTutor (port 8501) ...

set "KILLED=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8501 .*LISTENING"') do (
    echo   Killing PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
    set "KILLED=1"
)

if "%KILLED%"=="0" (
    echo   No process is listening on port 8501 - nothing to stop.
) else (
    timeout /t 1 /nobreak >nul
    echo   Done. MathTutor has been stopped.
    echo   Close the "MathTutor-streamlit" console window if it is still open.
)

endlocal

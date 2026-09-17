@echo off
chcp 65001 >nul
rem ============================================================
rem  MathTeacher Web Stopper
rem  Stops backend (port 8000) + frontend (port 5173)
rem  Double-click to quit the whole app
rem ============================================================
setlocal
cd /d "%~dp0"

title MathTeacher Stopper

echo.
echo  Stopping MathTeacher ...
echo.

rem ---- stop backend (port 8000) ------------------------------
set "KILLED=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    echo    Stopping backend PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
    set "KILLED=1"
)
if "%KILLED%"=="0" echo    [skip] backend not listening on 8000

rem ---- stop frontend (port 5173) -----------------------------
set "KILLED=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":5173 .*LISTENING"') do (
    echo    Stopping frontend PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
    set "KILLED=1"
)
if "%KILLED%"=="0" echo    [skip] frontend not listening on 5173

echo.
echo  Done. MathTeacher has been stopped.
echo  Close any remaining windows manually if needed.
echo.

endlocal

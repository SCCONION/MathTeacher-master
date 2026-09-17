@echo off
chcp 65001 >nul
rem ============================================================
rem  MathTeacher Web Launcher
rem  Starts FastAPI backend (8000) + React frontend (5173)
rem  Double-click to start the whole app
rem ============================================================
setlocal
cd /d "%~dp0"

title MathTeacher Launcher

rem ---- locate python (conda env "agent" preferred) ----------
set "PY=C:\Users\22094\.conda\envs\agent\python.exe"
if not exist "%PY%" set "PY=python"

rem ---- absolute paths (avoid "No module named 'api'" on reload)
set "APP_DIR=%~dp0src"
set "WEB_DIR=%~dp0web"

echo.
echo  ============================================================
echo   [1/2] Starting backend API   http://127.0.0.1:8000
echo   [2/2] Starting frontend      http://localhost:5173
echo  ============================================================
echo.

rem ---- start backend (new window, keeps logs) ----------------
start "MathTeacher-API" cmd /k ""%PY%" -m uvicorn api.main:app --app-dir "%APP_DIR%" --host 127.0.0.1 --port 8000 --reload"

rem ---- start frontend (new window, workdir = web) ------------
start "MathTeacher-Web" /D "%WEB_DIR%" cmd /k "npm run dev"

echo  Two windows started:
echo    - MathTeacher-API   (backend, close it to stop)
echo    - MathTeacher-Web   (frontend, close it to stop)
echo.
echo  Wait a few seconds, then open http://localhost:5173
echo.

timeout /t 6 /nobreak >nul
start "" "http://localhost:5173"

endlocal

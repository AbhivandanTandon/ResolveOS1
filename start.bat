@echo off
setlocal
title ResolveOS launcher
cd /d "%~dp0"

echo.
echo   ResolveOS
echo   ---------

where python >nul 2>nul || (echo Python was not found. Install Python 3.12 and try again. & pause & exit /b 1)
where npm >nul 2>nul || (echo Node.js was not found. Install Node.js and try again. & pause & exit /b 1)

rem First run only: create the Python environment and install packages.
if not exist "backend\.venv\Scripts\python.exe" (
  echo Setting up the backend. The first run takes several minutes...
  python -m venv "backend\.venv" || goto :failed
  "backend\.venv\Scripts\python.exe" -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu || goto :failed
  "backend\.venv\Scripts\python.exe" -m pip install -q -r "backend\requirements.txt" || goto :failed
)
if not exist "frontend\node_modules" (
  echo Setting up the frontend...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & goto :failed)
  popd
)

rem Skip Hugging Face network checks once the BGE model is cached, so models load faster.
if exist "%USERPROFILE%\.cache\huggingface\hub\models--BAAI--bge-small-en-v1.5" set HF_HUB_OFFLINE=1

rem Start each server in its own window, unless it is already running.
curl -s -o nul -m 2 http://127.0.0.1:8000/api/health
if errorlevel 1 (
  start "ResolveOS backend" /d "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
) else (
  echo Backend is already running.
)
curl -s -o nul -m 2 http://localhost:5173/
if errorlevel 1 (
  start "ResolveOS frontend" /d "%~dp0frontend" cmd /k "npm run dev"
) else (
  echo Frontend is already running.
)

echo Waiting for the servers to start...
set /a tries=0
:wait
set /a tries+=1
if %tries% gtr 60 (
  echo The servers did not start in time. Check the backend and frontend windows for errors.
  pause
  exit /b 1
)
ping -n 3 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:8000/api/health || goto :wait
curl -s -o nul -m 2 http://localhost:5173/ || goto :wait

if not defined RESOLVEOS_NO_BROWSER start "" http://localhost:5173
echo.
echo   ResolveOS is running at http://localhost:5173
echo   The ML models and demo cases finish loading in the background.
echo   To stop, close the backend and frontend windows.
echo.
if not defined RESOLVEOS_NO_BROWSER timeout /t 8 >nul
exit /b 0

:failed
echo.
echo Setup failed. See the messages above. Fix the problem, delete backend\.venv if it is incomplete, and run this again.
pause
exit /b 1

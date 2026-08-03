@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Vue Workflow Platform

echo ========================================
echo  Vue Workflow Platform
echo  1^) workflow_server  :8765
echo  2^) Vue frontend     :5173
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found. Install Python and add it to PATH.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found. Install Node.js and add it to PATH.
  pause
  exit /b 1
)

set "API_BAT=%~dp0start-workflow-server.bat"
set "FRONT=%~dp0workflow-platform"
set "URL=http://127.0.0.1:5173/"

if not exist "%API_BAT%" (
  echo [ERROR] missing start-workflow-server.bat
  pause
  exit /b 1
)
if not exist "%FRONT%\package.json" (
  echo [ERROR] missing workflow-platform
  pause
  exit /b 1
)

echo [1/2] Starting backend :8765 ...
start "workflow_server :8765" "%API_BAT%"

cd /d "%FRONT%"
if not exist "node_modules\" (
  echo First run: npm install ...
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed.
    pause
    exit /b 1
  )
)

echo [2/2] Starting Vue :5173 ...
echo Close this window to stop frontend.
echo Close the backend window to stop API.
echo.

start "" /b powershell -NoProfile -ExecutionPolicy Bypass -File "%FRONT%\wait-and-open.ps1" -Url "%URL%" -TimeoutSec 90

call npm run dev
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] Vite exit code %EXITCODE%
  pause
)
exit /b %EXITCODE%

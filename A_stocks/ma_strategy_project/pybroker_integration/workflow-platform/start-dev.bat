@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title Workflow Platform (Vue)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found. Install Node.js and add it to PATH.
  pause
  exit /b 1
)

if not exist "node_modules\" (
  echo First run: npm install ...
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed.
    pause
    exit /b 1
  )
)

set "URL=http://127.0.0.1:5173/"
echo Starting Vite at %URL%
echo Close this window to stop the server.
echo.

REM Start Vite in this window via a helper that waits then opens the browser
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wait-and-open.ps1" -Url "%URL%" -TimeoutSec 90

call npm run dev
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] Vite exited with code %EXITCODE%
  pause
)
exit /b %EXITCODE%

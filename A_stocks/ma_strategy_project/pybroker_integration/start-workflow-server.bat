@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title workflow_server :8765

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found. Install Python and add it to PATH.
  pause
  exit /b 1
)

REM If port 8765 is already listening, kill old process so new code is loaded.
powershell -NoProfile -Command "try { $cs = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop; foreach ($c in @($cs)) { if ($c.OwningProcess) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } } } catch { }" >nul 2>&1
timeout /t 1 >nul

echo Starting workflow_server ...
echo   http://127.0.0.1:8765/
echo Close this window to stop the backend.
echo.

python -m uvicorn workflow_server:app --host 127.0.0.1 --port 8765
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] workflow_server exit code %EXITCODE%
  pause
)
exit /b %EXITCODE%

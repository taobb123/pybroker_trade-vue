@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title workflow_server :8765

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未找到 python，请先安装并加入 PATH。
  pause
  exit /b 1
)

REM 若 8765 已在监听，则不再重复启动
powershell -NoProfile -Command "try { $c = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop; if ($c) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  echo [OK] workflow_server 已在 127.0.0.1:8765 运行，跳过启动。
  echo 浏览器旧台: http://127.0.0.1:8765/
  timeout /t 3 >nul
  exit /b 0
)

echo 启动 workflow_server ...
echo   http://127.0.0.1:8765/
echo 关闭本窗口即停止后端。
echo.

python -m uvicorn workflow_server:app --host 127.0.0.1 --port 8765
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] workflow_server 退出码 %EXITCODE%
  pause
)
exit /b %EXITCODE%

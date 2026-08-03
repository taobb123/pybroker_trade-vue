@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title 流控制台 · 后端+前端

echo ========================================
echo  流控制台一键启动
echo  1^) workflow_server  :8765
echo  2^) Vue 工作台       :5173
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未找到 python，请先安装并加入 PATH。
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未找到 npm，请先安装 Node.js 并加入 PATH。
  pause
  exit /b 1
)

set "API_BAT=%~dp0start-workflow-server.bat"
set "FRONT=%~dp0workflow-platform"
set "URL=http://127.0.0.1:5173/"

if not exist "%API_BAT%" (
  echo [ERROR] 缺少 start-workflow-server.bat
  pause
  exit /b 1
)
if not exist "%FRONT%\package.json" (
  echo [ERROR] 缺少 workflow-platform
  pause
  exit /b 1
)

echo [1/2] 启动 / 检查 backend :8765 ...
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

echo [2/2] 启动 Vue :5173 ...
echo 关闭本窗口停止前端；后端在独立窗口，关那个窗口停 API。
echo.

start "" /b powershell -NoProfile -ExecutionPolicy Bypass -File "%FRONT%\wait-and-open.ps1" -Url "%URL%" -TimeoutSec 90

call npm run dev
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] Vite 退出码 %EXITCODE%
  pause
)
exit /b %EXITCODE%

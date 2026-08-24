@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title 同步桌面自选分组

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 找不到 python，请先安装并加入 PATH。
  pause
  exit /b 1
)

python sync_mx_groups.py
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo 同步未完全成功，退出码 %EXITCODE%
)
pause
exit /b %EXITCODE%

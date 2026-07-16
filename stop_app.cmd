@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\stop_local_app.ps1" %*
if errorlevel 1 (
  echo.
  echo Stop failed.
  pause
  exit /b 1
)
exit /b 0

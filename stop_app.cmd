@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\stop_local_app.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Stop failed with exit code %EXIT_CODE%.
)
exit /b %EXIT_CODE%

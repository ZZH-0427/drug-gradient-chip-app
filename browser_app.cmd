@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%runtime\pythonw.exe" if exist "%ROOT%launcher.pyw" (
  "%ROOT%runtime\pythonw.exe" "%ROOT%launcher.pyw" --browser-mode %*
  set "EXIT_CODE=%ERRORLEVEL%"
  if not "%EXIT_CODE%"=="0" (
    echo.
    echo Application startup failed with exit code %EXIT_CODE%.
  )
  exit /b %EXIT_CODE%
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start_local_app.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Application startup failed with exit code %EXIT_CODE%.
)
exit /b %EXIT_CODE%

@echo off
setlocal
set "ROOT=%~dp0"
if /I "%~1"=="-NoBrowser" goto lifecycle
if /I "%~1"=="--NoBrowser" goto lifecycle
if exist "%ROOT%runtime\pythonw.exe" if exist "%ROOT%launcher.pyw" (
  "%ROOT%runtime\pythonw.exe" "%ROOT%launcher.pyw" %*
  set "EXIT_CODE=%ERRORLEVEL%"
  if not "%EXIT_CODE%"=="0" (
    echo.
    echo Application startup failed with exit code %EXIT_CODE%.
  )
  exit /b %EXIT_CODE%
)
:lifecycle
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start_local_app.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Application startup failed with exit code %EXIT_CODE%.
)
exit /b %EXIT_CODE%

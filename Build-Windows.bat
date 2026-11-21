@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Build-Windows.ps1"
if errorlevel 1 (
  echo.
  echo Danksy DroidOps build failed. Review artifacts\build.log.
  pause
  exit /b 1
)
echo.
echo Danksy DroidOps is ready in the release folder.
pause

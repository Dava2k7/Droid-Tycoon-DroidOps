@echo off
cd /d "%~dp0"
if not exist ".venv-build\Scripts\python.exe" (
  echo Danksy DroidOps: run Build-Windows.bat first, or install the release package.
  pause
  exit /b 1
)
".venv-build\Scripts\python.exe" -m droidops

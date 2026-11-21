@echo off
title Danksy DroidOps diagnostics
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Collect-Diagnostics.ps1"
pause

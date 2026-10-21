@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0run_local.ps1" -Demo -ShowTerminals -OpenBrowser -Detach
if errorlevel 1 pause

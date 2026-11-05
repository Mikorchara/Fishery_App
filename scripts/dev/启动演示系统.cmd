@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0run_local.ps1" -DataRoot "%~dp0..\..\outputs\qq-m3-real-test" -InteractiveMode -ShowTerminals -InteractiveScenario -OpenBrowser -Detach
if errorlevel 1 pause

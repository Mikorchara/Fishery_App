@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0run_local.ps1" -DataRoot "%~dp0..\..\outputs\qq-m3-real-test" -InteractiveMode -AutoDeviceReports -ShowTerminals -InteractiveScenario -OpenBrowser -Detach -EventTrial
if errorlevel 1 pause

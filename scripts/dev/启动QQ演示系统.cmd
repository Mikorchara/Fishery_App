@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0Start-ManagementStack.ps1" -Request "%~dp0..\..\outputs\qq-m3-real-config\request.json" -InteractiveMode -AutoDeviceReports -WithBot -NoAssistant -InteractiveScenario -OpenBrowser
if errorlevel 1 pause

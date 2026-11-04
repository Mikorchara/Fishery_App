@echo off
setlocal
if not exist "%~dp0..\..\sample.mp4" (
    echo LOCAL_DEMO_VIDEO_NOT_FOUND: put sample.mp4 in the project root.
    pause
    exit /b 1
)
powershell.exe -NoLogo -NoProfile -File "%~dp0run_local.ps1" -Demo -ShowTerminals -InteractiveMode -InteractiveScenario -OpenBrowser -Detach -ScoreTrial -DemoVideo "%~dp0..\..\sample.mp4"
if errorlevel 1 pause

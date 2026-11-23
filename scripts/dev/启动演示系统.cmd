@echo off
setlocal DisableDelayedExpansion
set "demo_video=%~f1"
if not defined demo_video set "demo_video=%~dp0..\..\sample.mp4"
if not exist "%demo_video%" set "demo_video="
if defined demo_video if exist "%demo_video%\*" set "demo_video="
powershell.exe -NoLogo -NoProfile -File "%~dp0run_local.ps1" -DataRoot "%~dp0..\..\outputs\qq-m3-real-test" -InteractiveMode -AutoDeviceReports -ShowTerminals -InteractiveScenario -OpenBrowser -Detach -ScoreTrial -EventTrial -DemoVideo "%demo_video%"
set "launch_exit=%errorlevel%"
if not "%launch_exit%"=="0" pause
exit /b %launch_exit%

@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0Start-BoardVideoDemo.ps1"
set "launch_exit=%errorlevel%"
if not "%launch_exit%"=="0" pause
exit /b %launch_exit%

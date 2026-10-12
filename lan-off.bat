@echo off
rem Closes the program for the network again: only this computer can open it.
setlocal enabledelayedexpansion
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call tools\lang.bat
if exist ".env" powershell -NoProfile -Command "$l=@(Get-Content .env | Where-Object { $_ -notmatch '^APP_BIND=' }); [IO.File]::WriteAllLines((Resolve-Path .env), $l)"
netsh advfirewall firewall delete rule name="TRS398 platform" >nul 2>&1
docker compose up -d app
echo !L_CLOSED!
pause

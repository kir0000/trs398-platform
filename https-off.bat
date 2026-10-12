@echo off
rem Switches HTTPS off (the program is then reachable on this computer only; lan-on.bat opens plain HTTP for the network again).
setlocal enabledelayedexpansion
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call tools\lang.bat
if exist ".env" powershell -NoProfile -Command "$l=@(Get-Content .env | Where-Object { $_ -notmatch '^(APP_BIND|HTTPS_ONLY)=' }); [IO.File]::WriteAllLines((Resolve-Path .env), $l)"
netsh advfirewall firewall delete rule name="TRS398 https" >nul 2>&1
docker compose --profile https stop https
docker compose up -d app
echo !L_CLOSED!
pause

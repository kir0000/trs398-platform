@echo off
rem Opens the program to the other computers of the local network (they use http://NAME-OF-THIS-PC:8000).
rem Needs administrator rights once (Windows Firewall); the window asks for them.
setlocal enabledelayedexpansion
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
call tools\lang.bat
docker info >nul 2>&1 || (echo !M_DOCKER_OFF! & pause & exit /b 1)
if not exist ".env" (echo !L_NOENV! & pause & exit /b 1)

powershell -NoProfile -Command "$l=@(Get-Content .env | Where-Object { $_ -notmatch '^APP_BIND=' }); $l+='APP_BIND=0.0.0.0'; [IO.File]::WriteAllLines((Resolve-Path .env), $l)"
netsh advfirewall firewall delete rule name="TRS398 platform" >nul 2>&1
netsh advfirewall firewall add rule name="TRS398 platform" dir=in action=allow protocol=TCP localport=8000 profile=private,domain >nul
docker compose up -d app

echo.
echo !L_OPEN!
echo   http://%COMPUTERNAME%:8000
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { '  http://' + $_.IPAddress + ':8000' }"
echo.
echo !L_NOTE1!
echo !L_NOTE2!
pause

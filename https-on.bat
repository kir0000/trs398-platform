@echo off
rem Encrypted access (HTTPS, port 8443) for the local network. Creates a self-signed certificate in certs\ if there is none
rem (or uses your own cert.pem / key.pem put there), closes the plain port 8000 to the network and opens 8443.
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
if not exist "certs" mkdir certs

if not exist "certs\cert.pem" (
  echo !H_MAKING!
  set "SAN="
  for /f "delims=" %%s in ('powershell -NoProfile -Command "$n=@('DNS:'+$env:COMPUTERNAME,'DNS:localhost'); $n+=Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.254.*' } | ForEach-Object { 'IP:'+$_.IPAddress }; $n -join ','"') do set "SAN=%%s"
  docker run --rm -v "%cd%\certs:/c" alpine/openssl req -x509 -newkey rsa:2048 -nodes -days 825 -keyout /c/key.pem -out /c/cert.pem -subj "/CN=%COMPUTERNAME%" -addext "subjectAltName=!SAN!" >nul 2>&1
  if not exist "certs\cert.pem" (echo !H_FAIL! & pause & exit /b 1)
)

powershell -NoProfile -Command "$l=@(Get-Content .env | Where-Object { $_ -notmatch '^(APP_BIND|HTTPS_ONLY)=' }); $l+='APP_BIND=127.0.0.1'; $l+='HTTPS_ONLY=1'; [IO.File]::WriteAllLines((Resolve-Path .env), $l)"
netsh advfirewall firewall delete rule name="TRS398 platform" >nul 2>&1
netsh advfirewall firewall delete rule name="TRS398 https" >nul 2>&1
netsh advfirewall firewall add rule name="TRS398 https" dir=in action=allow protocol=TCP localport=8443 profile=private,domain >nul
docker compose up -d app
docker compose --profile https up -d

echo.
echo !H_OPEN!
echo   https://%COMPUTERNAME%:8443
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { '  https://' + $_.IPAddress + ':8443' }"
echo.
echo !H_NOTE1!
echo !H_NOTE2!
pause

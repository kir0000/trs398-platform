@echo off
rem One-click start (Windows): checks the computer, creates .env with random secrets on the first run,
rem asks for the language (RU/EN), starts the program and opens the browser.
setlocal enabledelayedexpansion
cd /d "%~dp0"
call tools\lang.bat

if not exist ".env" (
  set "DEF=1"
  if "!L!"=="ru" set "DEF=2"
  choice /c 12 /n /t 20 /d !DEF! /m "!S_PICK!"
  if errorlevel 2 (set "L=ru") else (set "L=en")
  call tools\msg.!L!.bat
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\preflight.ps1" -Lang !L!
if errorlevel 1 (pause & exit /b 1)

if not exist ".env" (
  echo !S_CREATING!
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "function Rnd($n){ -join ((48..57)+(97..122) | Get-Random -Count $n | ForEach-Object {[char]$_}) };" ^
    "$lines = @(('TRS_OWNER_PASSWORD='+(Rnd 24)),('TRS_APP_PASSWORD='+(Rnd 24)),('TRS_READONLY_PASSWORD='+(Rnd 24)),('SESSION_SECRET='+(Rnd 48)),('TRS_LANG='+$env:L));" ^
    "[IO.File]::WriteAllLines((Join-Path (Get-Location) '.env'), $lines)"
  echo.
  echo !S_FIRST!
  echo.
)

if not exist "backups\requests" mkdir "backups\requests"
if exist "VERSION" set /p TRS_VERSION=<VERSION
rem a package for computers without the Internet carries the images: load them once
if exist "images\trs398-images.tar.gz" (
  docker image inspect ghcr.io/kir0000/trs398-platform:!TRS_VERSION! >nul 2>&1 || (echo !S_LOADING! & docker load -i images\trs398-images.tar.gz)
)
if exist "Dockerfile" (docker compose up -d --build) else (docker compose up -d)
if errorlevel 1 (echo !S_FAIL! & pause & exit /b 1)
docker exec -i trs398_db sh < db\migrate.sh

set "PORT=8000"
if exist ".env" for /f "tokens=2 delims==" %%p in ('findstr /b "APP_PORT=" .env') do set "PORT=%%p"
echo !S_WAIT!
for /l %%i in (1,1,30) do (
  curl -s -o nul http://127.0.0.1:!PORT!/healthz && goto ready
  ping -n 3 127.0.0.1 >nul
)
echo !S_TIMEOUT!
pause & exit /b 1

:ready
start "" http://localhost:!PORT!
echo !S_RUNNING! http://localhost:!PORT!
echo !S_HINT!
endlocal

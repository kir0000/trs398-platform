@echo off
rem Language / Язык: chooses the language of the scripts and of the program (TRS_LANG in .env) and restarts the program.
setlocal enabledelayedexpansion
cd /d "%~dp0"
call tools\lang.bat
if not exist ".env" (echo !L_NOENV! & pause & exit /b 1)
set "DEF=1"
if "!L!"=="ru" set "DEF=2"
choice /c 12 /n /t 20 /d !DEF! /m "!S_PICK!"
if errorlevel 2 (set "L=ru") else (set "L=en")
powershell -NoProfile -Command "$l=@(Get-Content .env | Where-Object { $_ -notmatch '^TRS_LANG=' }); $l+='TRS_LANG='+$env:L; [IO.File]::WriteAllLines((Resolve-Path .env), $l)"
call tools\msg.!L!.bat
echo !G_CHOSEN!
echo !G_RESTART!
docker compose up -d app
pause

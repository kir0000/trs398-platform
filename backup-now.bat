@echo off
rem Makes a database backup right now (it appears in the folder "backups").
setlocal enabledelayedexpansion
cd /d "%~dp0"
call tools\lang.bat
docker exec trs398_backup sh /backup.sh --once
if errorlevel 1 (echo !B_FAIL! & pause & exit /b 1)
echo !B_DONE!
pause

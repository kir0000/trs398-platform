@echo off
rem Stops the application. The data stay in the database and are there at the next start.bat.
setlocal enabledelayedexpansion
cd /d "%~dp0"
call tools\lang.bat
docker compose stop
echo !T_STOPPED!
pause

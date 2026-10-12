@echo off
rem Replaces the database with a backup.  Usage:  restore.bat [file]
rem   without a file: shows the newest backups and asks which one to use
rem   file: a name from the folder "backups" (also backups\keep\...) or a full path to a .sql.gz / .sql file
rem The current database is saved to backups\keep before it is replaced, so a wrong choice can be undone.
setlocal enabledelayedexpansion
cd /d "%~dp0"
call tools\lang.bat
docker info >nul 2>&1 || (echo !M_DOCKER_OFF! & pause & exit /b 1)
docker ps --format "{{.Names}}" | findstr "trs398_backup" >nul || (echo !R_NOTRUN! & pause & exit /b 1)

set "PICK=%~1"
if "%PICK%"=="" (
  echo !R_NEWEST!
  set n=0
  for /f "delims=" %%f in ('dir /b /o-d backups\trs398_*.sql.gz 2^>nul') do (
    set /a n+=1
    if !n! leq 10 ( echo   !n!. %%f & set "F!n!=%%f" )
  )
  if !n!==0 (echo !R_NONE! & pause & exit /b 1)
  set /p "NUM=!R_ASKNUM!"
  if "!NUM!"=="" set NUM=1
  call set "PICK=%%F!NUM!%%"
)
if "%PICK%"=="" (echo !R_WRONG! & pause & exit /b 1)

rem a path inside the folder "backups" is used as it is, a file from elsewhere is copied in first
set "ISREL=0"
if /i "!PICK:~0,8!"=="backups\" ( set "PICK=!PICK:~8!" & set "ISREL=1" )
if "!ISREL!"=="0" if exist "!PICK!" (
  for %%i in ("!PICK!") do set "NAME=%%~nxi"
  copy /y "!PICK!" "backups\!NAME!" >nul
  set "PICK=!NAME!"
)
set "PICK=!PICK:\=/!"

echo.
echo !R_REPLACED! !PICK!
echo !R_WARN!
set /p "OK=!R_TYPE!"
if /i not "!OK!"=="YES" (echo !R_CANCELLED! & pause & exit /b 0)

docker compose stop app
docker exec trs398_backup sh /restore.sh "!PICK!"
if errorlevel 1 (echo. & echo !R_FAILED! & docker compose start app & pause & exit /b 1)
docker compose start app
echo.
echo !R_OK!
pause

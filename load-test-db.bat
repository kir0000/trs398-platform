@echo off
rem Loads a database file (trs398_*.db.gz made by tools\make_transfer.py or by the backup of the program, or a plain .db) into THIS copy of the program.
rem   double-click: the newest trs398_*.db.gz next to this file or in its "transfer" folder is loaded
rem   or drag a file (or a folder) onto this file
rem The database of this program is REPLACED; a copy of it is kept in the folder backups\keep.
rem Only the program that runs from THIS folder is closed (other copies of TRS398 keep running).
rem Without the question: set TRS_YES=1 before the start.
chcp 65001 >nul
cd /d "%~dp0"
if not exist "TRS398.exe" (echo Put this file next to TRS398.exe. & pause & exit /b 1)
set "SRC=%~1"
if "%SRC%"=="" set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC%."
echo.
echo  Source: %SRC%
echo  The database of this program will be REPLACED (the old one is kept in backups\keep).
if /i not "%TRS_YES%"=="1" (
  set /p OK="Type YES to continue: "
  if /i not "%OK%"=="YES" (echo Cancelled. & pause & exit /b 0)
)
powershell -NoProfile -Command "$me = Join-Path '%~dp0' 'TRS398.exe'; Get-Process TRS398 -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $me } | Stop-Process -Force" >nul 2>&1
ping -n 3 127.0.0.1 >nul
start /wait "" "TRS398.exe" restore "%SRC%" --yes
if errorlevel 1 (echo The database was NOT changed. & pause & exit /b 1)
echo.
echo Starting the program...
start "" "TRS398.exe"

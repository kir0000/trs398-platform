@echo off
rem Updates the program to the newest version and restarts it. Data, passwords and backups are kept.
setlocal enabledelayedexpansion
cd /d "%~dp0"
call tools\lang.bat
docker info >nul 2>&1 || (echo !M_DOCKER_OFF! & pause & exit /b 1)
echo !U_BACKUP!
docker exec trs398_backup sh /backup.sh --once
if exist ".git" (
  git pull --ff-only || (echo !U_GITFAIL! & pause & exit /b 1)
) else if not exist "images\trs398-images.tar.gz" (
  echo !U_NOGIT!
  pause & exit /b 0
)
if exist "VERSION" set /p TRS_VERSION=<VERSION
if exist "images\trs398-images.tar.gz" (
  docker image inspect ghcr.io/kir0000/trs398-app:!TRS_VERSION! >nul 2>&1 || (echo !S_LOADING! & docker load -i images\trs398-images.tar.gz)
)
if exist "Dockerfile" (docker compose up -d --build) else (docker compose up -d)
docker exec -i trs398_db sh < db\migrate.sh
echo !U_DONE! http://localhost:8000
pause

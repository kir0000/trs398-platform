#!/bin/sh
# Replace the working database with a backup. Runs in the "backup" container:
#   docker exec trs398_backup sh /restore.sh <file>        (file name inside /backups, e.g. trs398_2026-10-12_020000.sql.gz,
#                                                           keep/before_new_database_....sql.gz, or a plain .sql file)
# The application must be stopped first (restore.bat / restore.sh do that). Before anything is replaced the current
# database is saved to /backups/keep/before_restore_<time>.sql.gz, so a wrong choice can be undone the same way.
set -eu
[ $# -eq 1 ] || { echo "usage: restore.sh <backup file>" >&2; exit 2; }
BACKUP_DIR="${BACKUP_DIR:-/backups}"
case "$1" in /*) FILE="$1" ;; *) FILE="$BACKUP_DIR/$1" ;; esac
[ -s "$FILE" ] || { echo "backup not found or empty: $FILE" >&2; exit 2; }
case "$FILE" in
  *.gz) gzip -t "$FILE" || { echo "the file is damaged (gzip test failed): $FILE" >&2; exit 2; }; READ="gunzip -c" ;;
  *)    READ="cat" ;;
esac
PSQL="psql -h db -U trs_owner -v ON_ERROR_STOP=1 -q"

mkdir -p "$BACKUP_DIR/keep"
SAFE="$BACKUP_DIR/keep/before_restore_$(date +%Y-%m-%d_%H%M%S).sql.gz"
if $PSQL -d postgres -tA -c "SELECT 1 FROM pg_database WHERE datname = 'trs398'" | grep -q 1; then
  pg_dump -h db -U trs_owner -d trs398 --no-owner | gzip > "$SAFE"
  echo "current database saved: $SAFE ($(wc -c < "$SAFE") bytes)"
fi

echo "restoring from $FILE ..."
$PSQL -d postgres -c "DROP DATABASE IF EXISTS trs398 WITH (FORCE)" -c "CREATE DATABASE trs398 OWNER trs_owner"
if ! $READ "$FILE" | $PSQL -d trs398 > /dev/null; then
  echo "RESTORE FAILED. The previous database is in $SAFE; restore it with: restore <that file>" >&2
  exit 1
fi
echo "restored. Rows now:"
$PSQL -d trs398 -tA -F ' ' -c "SELECT 'users', count(*) FROM users UNION ALL SELECT 'beams', count(*) FROM beams UNION ALL SELECT 'calibrations', count(*) FROM calibrations UNION ALL SELECT 'measurements', count(*) FROM measurement_sessions UNION ALL SELECT 'results', count(*) FROM results"

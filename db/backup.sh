#!/bin/sh
# Database backups, runs in the "backup" container (PGPASSWORD comes from the environment).
#   (no argument)  one dump at start when there is none from the last 20 hours, then every day at BACKUP_HOUR
#                  (container time, UTC); a dump can also be requested from the "Backups" page of the web application
#                  (the app drops a file into /backups/requests) or by `backup-now.bat`; old dumps are pruned
#   --once         one dump now and exit (used by backup-now)
# Files: /backups/trs398_YYYY-MM-DD_HHMMSS.sql.gz; /backups/keep/ is never pruned (restore.sh stores its safety copies there).
set -eu
BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
BACKUP_HOUR="${BACKUP_HOUR:-02}"
REQUESTS="$BACKUP_DIR/requests"
mkdir -p "$BACKUP_DIR" "$REQUESTS" "$BACKUP_DIR/keep"

do_backup() {
  f="$BACKUP_DIR/trs398_$(date +%Y-%m-%d_%H%M%S).sql.gz"
  if pg_dump -h db -U trs_owner -d trs398 --no-owner | gzip > "$f.tmp" && [ -s "$f.tmp" ]; then
    mv "$f.tmp" "$f"
    echo "$(date '+%F %T') backup written: $f ($(wc -c < "$f") bytes)"
  else
    rm -f "$f.tmp"
    echo "$(date '+%F %T') backup FAILED" >&2
    return 1
  fi
  find "$BACKUP_DIR" -maxdepth 1 -name 'trs398_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
}

if [ "${1:-}" = "--once" ]; then
  do_backup
  exit $?
fi

if [ -z "$(find "$BACKUP_DIR" -maxdepth 1 -name 'trs398_*.sql.gz' -mmin -1200 2>/dev/null)" ]; then
  do_backup || true
fi

while true; do
  now=$(date +%s)
  target=$(date -d "today ${BACKUP_HOUR}:00" +%s)
  if [ "$target" -le "$now" ]; then target=$(date -d "tomorrow ${BACKUP_HOUR}:00" +%s); fi
  echo "$(date '+%F %T') next backup at $(date -d "@$target" '+%F %T')"
  while [ "$(date +%s)" -lt "$target" ]; do
    if [ -e "$REQUESTS/backup-now" ]; then
      rm -f "$REQUESTS/backup-now"
      echo "$(date '+%F %T') backup requested from the application"
      do_backup || true
    fi
    sleep 10
  done
  do_backup || true
done

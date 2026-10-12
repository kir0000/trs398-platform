#!/bin/sh
# Replace the database with a backup (Linux/macOS).  Usage: ./restore.sh [file in backups/ | path]
# The current database is saved to backups/keep first.
cd "$(dirname "$0")" || exit 1
f="${1:-}"
if [ -z "$f" ]; then
  echo "Newest backups:"; ls -1t backups/trs398_*.sql.gz 2>/dev/null | head -10 | nl
  printf "Number [1 = newest]: "; read -r n; n="${n:-1}"
  f="$(ls -1t backups/trs398_*.sql.gz | sed -n "${n}p")"
fi
[ -n "$f" ] || { echo "No backup chosen." >&2; exit 1; }
if [ -f "$f" ]; then case "$f" in backups/*) ;; *) cp "$f" "backups/$(basename "$f")"; f="backups/$(basename "$f")" ;; esac; fi
name="${f#backups/}"
printf "The database will be REPLACED by %s. Type YES to continue: " "$name"; read -r ok
[ "$ok" = "YES" ] || { echo "Cancelled."; exit 0; }
docker compose stop app
docker exec trs398_backup sh /restore.sh "$name" || { echo "Restore failed." >&2; docker compose start app; exit 1; }
docker compose start app
echo "Restored. Open http://localhost:8000"

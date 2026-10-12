#!/bin/sh
# Brings an existing database up to the schema of db/init/*.sql. Runs inside the db container (start.bat / update.bat call it):
#   docker exec -i trs398_db sh < db/migrate.sh
# New databases get every file from the image entry point; this covers databases created by an older version.
# Files 001-008 are treated as applied on a database that predates the tracking table; later files are written to be repeatable.
set -e
P="psql -v ON_ERROR_STOP=1 -q -U $POSTGRES_USER -d $POSTGRES_DB"
$P -c "CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());"
if [ "$($P -Atc "SELECT count(*) FROM schema_migrations")" = "0" ] && [ "$($P -Atc "SELECT to_regclass('public.measurement_sessions') IS NOT NULL")" = "t" ]; then
  for f in /docker-entrypoint-initdb.d/00[0-8]_*.sql; do
    $P -c "INSERT INTO schema_migrations(name) VALUES ('$(basename "$f")') ON CONFLICT DO NOTHING;"
  done
fi
for f in /docker-entrypoint-initdb.d/*.sql; do
  n=$(basename "$f")
  if [ "$($P -Atc "SELECT count(*) FROM schema_migrations WHERE name = '$n'")" = "0" ]; then
    echo "applying $n"
    $P -f "$f"
    $P -c "INSERT INTO schema_migrations(name) VALUES ('$n');"
  fi
done

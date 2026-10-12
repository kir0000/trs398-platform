#!/bin/sh
# Creates the application and read-only database roles. Passwords come from the environment.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE trs_app LOGIN PASSWORD '${TRS_APP_PASSWORD}';
CREATE ROLE trs_readonly LOGIN PASSWORD '${TRS_READONLY_PASSWORD}';
EOSQL

#!/usr/bin/env bash
set -euo pipefail

# Postgres's own docker-entrypoint scans every top-level *.sql/*.sh file
# directly under /docker-entrypoint-initdb.d/ and runs each one
# independently. roles.sql and the migration files are NOT safe to run
# that way (roles.sql needs psql variables set, migrations need to run
# as app_migrator, not the postgres superuser). So the real script tree
# is mounted elsewhere (/app-db) where the scanner won't touch it, and
# this is the only file the scanner finds -- it just delegates.
bash /app-db/bootstrap.sh

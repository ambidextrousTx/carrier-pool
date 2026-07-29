#!/usr/bin/env bash
set -euo pipefail

# Bootstraps the database: creates roles, applies migrations as the
# owning role (app_migrator), sets up default privileges for the
# runtime role (app_runtime). Idempotent -- safe to re-run.
#
# Used two ways:
#   1. Locally, by a developer, against a Postgres they started themselves.
#   2. By docker-compose, mounted into /docker-entrypoint-initdb.d/, where
#      the official postgres image runs it automatically on first boot
#      of an empty data volume.
# Both paths run this exact script -- there is no separate "docker
# version" of this logic to drift out of sync.

: "${PGPORT:=5432}"
: "${POSTGRES_DB:=carrier_recs}"
: "${POSTGRES_USER:=postgres}"        # bootstrap superuser
: "${APP_MIGRATOR_PASSWORD:=migrator_dev_pw}"
: "${APP_RUNTIME_PASSWORD:=runtime_dev_pw}"

# Auth for the bootstrap superuser connection: the official postgres
# docker image exposes its password as POSTGRES_PASSWORD. Prefer that;
# fall back to a manually-exported PGPASSWORD for local/by-hand runs.
export PGPASSWORD="${POSTGRES_PASSWORD:-${PGPASSWORD:-}}"

# During docker-entrypoint-initdb.d processing, Postgres runs a
# TEMPORARY server that only listens on the Unix socket, not TCP (so
# nothing can reach it over the network before the container is fully
# up). Forcing a host connection here would fail with "connection
# refused" even though the server is genuinely running. So: no -h flag
# by default (psql then uses the Unix socket automatically), and only
# add one if PGHOST is explicitly set -- e.g. for local/manual runs
# against a server that isn't in the same container/socket namespace.
PSQL_HOST_ARGS=()
if [ -n "${PGHOST:-}" ]; then
    PSQL_HOST_ARGS=(-h "$PGHOST")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/2] Creating roles and default privileges (as $POSTGRES_USER)"
psql -v ON_ERROR_STOP=1 "${PSQL_HOST_ARGS[@]}" -p "$PGPORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v migrator_pw="$APP_MIGRATOR_PASSWORD" \
    -v runtime_pw="$APP_RUNTIME_PASSWORD" \
    -f "$SCRIPT_DIR/roles.sql"

echo "==> [2/2] Applying migrations (as app_migrator)"
for f in "$SCRIPT_DIR"/migrations/*.sql; do
    echo "    - $(basename "$f")"
    PGPASSWORD="$APP_MIGRATOR_PASSWORD" psql -v ON_ERROR_STOP=1 "${PSQL_HOST_ARGS[@]}" -p "$PGPORT" \
        -U app_migrator -d "$POSTGRES_DB" -f "$f"
done

echo "==> Bootstrap complete"

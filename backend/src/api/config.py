import os

# Same env var conventions as scripts/seed_data.py -- deliberately not
# introducing a second way to configure the DB connection.
DB_HOST = os.environ.get("PGHOST", "localhost")
DB_NAME = os.environ.get("PGDATABASE", "carrier_recs")

# The API is read-only and never needs elevated privileges -- it only
# ever connects as app_runtime, never app_migrator. That's not just
# convenient, it's the point: the API process physically cannot bypass
# RLS even if a route forgot to call set_tenant_context (it wouldn't
# return the right *data*, but it can't return *another broker's* data
# either way).
RUNTIME_DSN = f"host={DB_HOST} dbname={DB_NAME} user=app_runtime password={os.environ.get('APP_RUNTIME_PASSWORD', 'runtime_dev_pw')}"

POOL_MIN_SIZE = int(os.environ.get("API_POOL_MIN_SIZE", "1"))
POOL_MAX_SIZE = int(os.environ.get("API_POOL_MAX_SIZE", "10"))

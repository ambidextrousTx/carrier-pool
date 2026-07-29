-- roles.sql
--
-- Run once, as the bootstrap superuser, before any migrations. Sets up
-- two roles with deliberately different privilege levels:
--
-- app_migrator: owns the schema, runs migrations. Bypasses RLS (owners
--               do, by default) -- that's fine, it's never used to serve
--               tenant traffic, only trusted migration/admin scripts.
-- app_runtime:  what the backend actually connects as. Owns nothing,
--               is not superuser, has no BYPASSRLS. RLS applies to it
--               unconditionally -- this is the role that makes the
--               isolation guarantee real rather than aspirational.
--
-- Passwords are passed in as psql variables (see bootstrap.sh), not
-- hardcoded here.

SELECT format('CREATE ROLE app_migrator LOGIN PASSWORD %L CREATEDB', :'migrator_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_migrator')
\gexec

SELECT format(
    'CREATE ROLE app_runtime LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
    :'runtime_pw'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_runtime')
\gexec

-- Postgres 15+ no longer grants CREATE on the public schema to PUBLIC by
-- default. app_migrator needs it to create the tables our migrations define.
GRANT CREATE, USAGE ON SCHEMA public TO app_migrator;
GRANT USAGE ON SCHEMA public TO app_runtime;

-- The important part: any table app_migrator creates FROM THIS POINT
-- FORWARD automatically grants CRUD to app_runtime. This means a future
-- migration that adds a new tenant-scoped table does not require anyone
-- to remember to also update this file -- the grant just happens. It
-- does NOT retroactively apply to already-existing tables, which is why
-- this runs before any migrations.
ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;

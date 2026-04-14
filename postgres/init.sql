-- ============================================================
-- PostgreSQL initialisation script
-- Creates separate databases for n8n and the API
-- Runs once on first container start
-- ============================================================

-- Variables are injected by docker-compose via env
-- (using shell substitution in entrypoint)

\echo 'Creating n8n database...'
SELECT 'CREATE DATABASE n8n' WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'n8n'
)\gexec

\echo 'Creating appdb database...'
SELECT 'CREATE DATABASE appdb' WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'appdb'
)\gexec

-- Grant privileges to the main user on both databases
GRANT ALL PRIVILEGES ON DATABASE n8n TO CURRENT_USER;
GRANT ALL PRIVILEGES ON DATABASE appdb TO CURRENT_USER;

\echo 'Databases ready.'

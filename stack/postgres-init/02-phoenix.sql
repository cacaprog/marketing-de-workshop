-- Fase 3 — banco do Phoenix (traces); só estudo local.
-- Roda pelo serviço one-off `db-init` a cada `make up`, de forma idempotente (como o 01-marquez.sql).
-- O Phoenix guarda os traces aqui até o `make reset`. Requer PostgreSQL >= 14 (a stack usa o 16).
SELECT 'CREATE ROLE phoenix LOGIN PASSWORD ''phoenix'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'phoenix')\gexec
SELECT 'CREATE DATABASE phoenix OWNER phoenix'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')\gexec

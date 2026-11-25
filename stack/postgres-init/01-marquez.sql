-- Fase 2: banco do Marquez (linhagem) no MESMO Postgres da stack, criado de forma idempotente.
-- Roda pelo serviço one-off `marquez-db-init` a cada `make up` (um script do initdb só rodaria
-- com o volume vazio). Usuário, senha e banco "marquez" são os fixos do marquez.dev.yml 0.50.0.
SELECT 'CREATE ROLE marquez LOGIN PASSWORD ''marquez'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marquez')\gexec
SELECT 'CREATE DATABASE marquez OWNER marquez'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'marquez')\gexec

-- Fase 4 — catálogo do DuckLake (metadados das camadas de dados); só estudo local.
-- Roda pelo serviço one-off `db-init` a cada `make up`, de forma idempotente (como o 02-phoenix.sql).
-- Os arquivos Parquet ficam em stack/data/lake/; aqui ficam só as tabelas do catálogo (snapshots, esquemas, arquivos).
SELECT 'CREATE ROLE ducklake LOGIN PASSWORD ''ducklake'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ducklake')\gexec
SELECT 'CREATE DATABASE ducklake OWNER ducklake'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ducklake')\gexec

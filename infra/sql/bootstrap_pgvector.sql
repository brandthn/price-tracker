-- Bootstrap one-shot Phase 4 : active l'extension pgvector sur la base
-- `price_tracker`. À exécuter UNE FOIS après `terraform apply`, connecté
-- avec l'utilisateur applicatif `pt_app` via Cloud SQL Studio ou Cloud SQL
-- Auth Proxy (cf. runbook dans infra/README.md §"Bootstrap pgvector").
--
-- Idempotent (IF NOT EXISTS) : peut être rejoué sans risque.

CREATE EXTENSION IF NOT EXISTS vector;

-- Vérification rapide : doit afficher 'vector' avec sa version installée.
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

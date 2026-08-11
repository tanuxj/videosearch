-- Enable the pgvector extension (idempotent).
-- This runs against the database named by POSTGRES_DB on first container boot.
CREATE EXTENSION IF NOT EXISTS vector;

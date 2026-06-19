-- RAG: tabela de conhecimento BMST
-- Executar no Supabase SQL Editor ANTES de correr ingest.py
-- Requer extensão pgvector activada no projecto Supabase.

-- 1. Extensão vectorial
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Tabela de documentos
CREATE TABLE IF NOT EXISTS documents (
  id        bigserial PRIMARY KEY,
  conteudo  text          NOT NULL,
  metadata  jsonb         NOT NULL DEFAULT '{}',
  embedding vector(1536)  NOT NULL
);

-- 3. Índice ANN para pesquisa rápida por similaridade cosseno
--    lists=10 é adequado para corpora pequenos (< 1 000 linhas).
--    Aumenta para sqrt(n_rows) quando o corpus crescer.
CREATE INDEX IF NOT EXISTS idx_documents_embedding
  ON documents
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

-- 4. Função RPC usada pelo agente para pesquisa semântica
--    Recebe o embedding da pergunta e devolve os top-k chunks mais próximos.
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_count     int DEFAULT 3
)
RETURNS TABLE (
  id         bigint,
  conteudo   text,
  metadata   jsonb,
  similarity float
)
LANGUAGE sql STABLE
AS $$
  SELECT
    id,
    conteudo,
    metadata,
    1 - (embedding <=> query_embedding) AS similarity
  FROM documents
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;

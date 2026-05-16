-- Migração: adicionar colunas em falta à tabela lusambu_leads existente
-- Executar no Supabase SQL Editor se a tabela já existir.
-- Se estiver a criar de raiz, usa supabase_schema.sql em vez deste ficheiro.

ALTER TABLE lusambu_leads
    ADD COLUMN IF NOT EXISTS scheduled_time  TEXT,
    ADD COLUMN IF NOT EXISTS is_objecting    BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS wants_human     BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ready_to_close  BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS prompt_variant  TEXT,
    ADD COLUMN IF NOT EXISTS followup_count  INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_contact_at TIMESTAMPTZ DEFAULT NOW();

-- Actualiza o índice de last_contact_at (remove o antigo se existir por outro nome)
DROP INDEX IF EXISTS idx_lusambu_leads_created_at;
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_last_contact ON lusambu_leads(last_contact_at DESC);

-- Função RPC para incrementar followup_count atomicamente
CREATE OR REPLACE FUNCTION increment_followup_count(p_whatsapp TEXT)
RETURNS VOID AS $$
BEGIN
    UPDATE lusambu_leads
    SET followup_count  = COALESCE(followup_count, 0) + 1,
        last_contact_at = NOW()
    WHERE whatsapp = p_whatsapp;
END;
$$ LANGUAGE plpgsql;

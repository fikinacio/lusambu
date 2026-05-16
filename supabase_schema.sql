-- Tabela de leads do agente Lusambu
-- Executar no Supabase SQL Editor

CREATE TABLE IF NOT EXISTS lusambu_leads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp        TEXT UNIQUE NOT NULL,
    name            TEXT,
    company         TEXT,
    sector          TEXT,
    pain_point      TEXT,
    size            TEXT,
    scheduled_time  TEXT,                          -- dia/hora preferida para chamada
    classification  TEXT DEFAULT 'unknown',        -- hot | warm | cold | unknown
    stage           TEXT DEFAULT 'qualify',        -- qualify | pitch | objection | closing | escalado | descartado | end
    status          TEXT DEFAULT 'activo',         -- activo | escalado | descartado | fechado
    has_business    BOOLEAN,
    is_objecting    BOOLEAN DEFAULT FALSE,
    wants_human     BOOLEAN DEFAULT FALSE,
    ready_to_close  BOOLEAN DEFAULT FALSE,
    prompt_variant  TEXT,                          -- A | B (teste A/B de pitch)
    followup_count  INTEGER DEFAULT 0,
    last_contact_at TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Índices úteis
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_status ON lusambu_leads(status);
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_classification ON lusambu_leads(classification);
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_last_contact ON lusambu_leads(last_contact_at DESC);

-- Trigger para actualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER lusambu_leads_updated_at
    BEFORE UPDATE ON lusambu_leads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Função RPC para incrementar followup_count atomicamente
-- Chamada por increment_followup() em supabase_client.py
CREATE OR REPLACE FUNCTION increment_followup_count(p_whatsapp TEXT)
RETURNS VOID AS $$
BEGIN
    UPDATE lusambu_leads
    SET followup_count  = COALESCE(followup_count, 0) + 1,
        last_contact_at = NOW()
    WHERE whatsapp = p_whatsapp;
END;
$$ LANGUAGE plpgsql;

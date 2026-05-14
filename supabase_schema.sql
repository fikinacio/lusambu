-- Tabela de leads do agente Lusambu
-- Executar no Supabase SQL Editor

CREATE TABLE IF NOT EXISTS lusambu_leads (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp    TEXT UNIQUE NOT NULL,
    name        TEXT,
    company     TEXT,
    sector      TEXT,
    pain_point  TEXT,
    size        TEXT,
    classification TEXT DEFAULT 'unknown',   -- hot | warm | cold | unknown
    stage       TEXT DEFAULT 'qualify',      -- qualify | pitch | objection | escalado | descartado | end
    status      TEXT DEFAULT 'activo',       -- activo | escalado | descartado | fechado
    has_business BOOLEAN,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Índices úteis
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_status ON lusambu_leads(status);
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_classification ON lusambu_leads(classification);
CREATE INDEX IF NOT EXISTS idx_lusambu_leads_created_at ON lusambu_leads(created_at DESC);

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

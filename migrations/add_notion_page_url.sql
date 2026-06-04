-- Migration: adicionar coluna notion_page_url à tabela invoice_drafts
ALTER TABLE invoice_drafts ADD COLUMN IF NOT EXISTS notion_page_url TEXT;

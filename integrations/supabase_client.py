import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_KEY", ""),
        )
    return _supabase


_TRANSIENT_FIELDS = {"confirms_data"}  # campos do LLM que não existem como colunas no DB


async def upsert_lead(lead_data: dict) -> bool:
    """Insere ou actualiza lead na tabela lusambu_leads. Chave: 'whatsapp'."""
    try:
        db = get_supabase()
        clean_data = {k: v for k, v in lead_data.items() if v is not None and k not in _TRANSIENT_FIELDS}
        clean_data["last_contact_at"] = datetime.now(timezone.utc).isoformat()
        db.table("lusambu_leads").upsert(clean_data, on_conflict="whatsapp").execute()
        logger.info(f"Lead guardado: {clean_data.get('whatsapp', '—')}")
        return True
    except Exception as e:
        logger.error(f"Erro ao guardar lead: {e}")
        return False


async def get_stale_leads(hours: int = 24) -> list[dict]:
    """Leads activos sem resposta há mais de `hours` horas, com menos de 2 follow-ups."""
    try:
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, sector, stage, followup_count")
            .lt("last_contact_at", cutoff)
            .lt("followup_count", 2)
            .neq("status", "descartado")
            .neq("status", "escalado")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar leads para follow-up: {e}")
        return []


async def get_all_leads() -> list[dict]:
    """Todos os leads ordenados por último contacto."""
    try:
        db = get_supabase()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, company, sector, classification, stage, status, pain_point, followup_count, last_contact_at, prompt_variant")
            .order("last_contact_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao carregar leads: {e}")
        return []


async def get_outreach_message(number: str) -> Optional[str]:
    """Busca a última mensagem outbound enviada a este número via WhatsApp.

    Fluxo: empresas.whatsapp = number → mensagens.empresa_id
    Filtra: direcao='saida', canal='whatsapp'. Devolve mensagens.conteudo.
    """
    try:
        db = get_supabase()
        # 1. Encontrar empresa pelo número de WhatsApp
        empresa = (
            db.table("empresas")
            .select("id")
            .eq("whatsapp", number)
            .limit(1)
            .execute()
        )
        if not empresa.data:
            return None
        empresa_id = empresa.data[0]["id"]
        # 2. Buscar última mensagem outbound enviada a essa empresa
        result = (
            db.table("mensagens")
            .select("conteudo")
            .eq("empresa_id", empresa_id)
            .eq("direcao", "saida")
            .eq("canal", "whatsapp")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("conteudo")
        return None
    except Exception as e:
        logger.error(f"Erro ao carregar contexto de prospecção para {number}: {e}")
        return None


async def increment_followup(whatsapp: str) -> None:
    """Regista o follow-up enviado e actualiza o timestamp."""
    try:
        db = get_supabase()
        db.rpc("increment_followup_count", {"p_whatsapp": whatsapp}).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar followup_count para {whatsapp}: {e}")


async def get_outbound_stale_leads(followup_count: int, hours: int) -> list[dict]:
    """Leads outbound (status='enviado') sem resposta há mais de `hours` horas, com followup_count exacto."""
    try:
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, sector, pain_point, followup_count")
            .eq("status", "enviado")
            .eq("followup_count", followup_count)
            .lt("last_contact_at", cutoff)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar outbound stale leads (count={followup_count}): {e}")
        return []


async def get_company_config() -> dict:
    """Lê todos os pares chave-valor de company_config e devolve como dict."""
    try:
        db = get_supabase()
        result = db.table("company_config").select("key, value").execute()
        return {row["key"]: row["value"] for row in (result.data or [])}
    except Exception as e:
        logger.error(f"Erro ao carregar company_config: {e}")
        return {}


async def get_lead_for_proposal(whatsapp: str) -> Optional[dict]:
    """Lê dados completos do lead para gerar proposta."""
    try:
        db = get_supabase()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, company, sector, pain_point, notas_sales, valor_negociado, status")
            .eq("whatsapp", whatsapp)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao ler lead para proposta ({whatsapp}): {e}")
        return None


async def save_proposal_draft(data: dict) -> Optional[str]:
    """Insere rascunho de proposta. Devolve o UUID gerado."""
    try:
        db = get_supabase()
        result = db.table("proposal_drafts").insert(data).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Erro ao guardar rascunho de proposta: {e}")
        return None


async def update_proposal_draft(draft_id: str, updates: dict) -> None:
    """Actualiza campos de um rascunho existente."""
    try:
        db = get_supabase()
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        db.table("proposal_drafts").update(updates).eq("id", draft_id).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar rascunho {draft_id}: {e}")


async def get_pending_proposal_for_fidel() -> Optional[dict]:
    """Devolve o rascunho mais recente em estado pending ou editing."""
    try:
        db = get_supabase()
        result = (
            db.table("proposal_drafts")
            .select("*")
            .in_("status", ["pending", "editing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao buscar proposta pendente: {e}")
        return None

import os
import logging
from datetime import datetime, timezone, timedelta
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


async def upsert_lead(lead_data: dict) -> bool:
    """Insere ou actualiza lead na tabela lusambu_leads. Chave: 'whatsapp'."""
    try:
        db = get_supabase()
        clean_data = {k: v for k, v in lead_data.items() if v is not None}
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
            .select("whatsapp, name, company, sector, classification, stage, status, pain_point, followup_count, last_contact_at")
            .order("last_contact_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao carregar leads: {e}")
        return []


async def increment_followup(whatsapp: str) -> None:
    """Regista o follow-up enviado e actualiza o timestamp."""
    try:
        db = get_supabase()
        db.rpc("increment_followup_count", {"p_whatsapp": whatsapp}).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar followup_count para {whatsapp}: {e}")

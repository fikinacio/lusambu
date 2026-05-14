import os
import logging
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
    """
    Insere ou actualiza lead na tabela lusambu_leads.
    Chave de upsert: campo 'whatsapp'.
    """
    try:
        db = get_supabase()
        # Remove campos None para não sobrescrever dados existentes
        clean_data = {k: v for k, v in lead_data.items() if v is not None}
        db.table("lusambu_leads").upsert(clean_data, on_conflict="whatsapp").execute()
        logger.info(f"Lead guardado: {clean_data.get('whatsapp', '—')}")
        return True
    except Exception as e:
        logger.error(f"Erro ao guardar lead: {e}")
        return False

import logging
import os
from datetime import date

import httpx

logger = logging.getLogger(__name__)

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_PROJECTS_DB_ID = os.getenv("NOTION_PROJECTS_DB_ID", "")
NOTION_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def create_notion_project(
    empresa: str,
    sector: str,
    valor: str,
    whatsapp: str,
    invoice_number: str,
) -> str:
    """Cria página de projecto na BD do Notion. Devolve URL da página ou string vazia se falhar."""
    if not NOTION_API_KEY or not NOTION_PROJECTS_DB_ID:
        logger.warning("NOTION_API_KEY ou NOTION_PROJECTS_DB_ID não configurados — a saltar criação de projecto.")
        return ""

    payload = {
        "parent": {"database_id": NOTION_PROJECTS_DB_ID},
        "properties": {
            "Nome": {
                "title": [{"text": {"content": f"{empresa} — {invoice_number}"}}]
            },
            "Cliente": {
                "rich_text": [{"text": {"content": empresa}}]
            },
            "Sector": {
                "select": {"name": sector or "Outro"}
            },
            "Valor": {
                "rich_text": [{"text": {"content": valor}}]
            },
            "Estado": {
                "select": {"name": "Em curso"}
            },
            "Data de Início": {
                "date": {"start": date.today().isoformat()}
            },
            "WhatsApp": {
                "rich_text": [{"text": {"content": whatsapp}}]
            },
            "Número Factura": {
                "rich_text": [{"text": {"content": invoice_number}}]
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.notion.com/v1/pages",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            url = data.get("url", "")
            logger.info(f"Projecto Notion criado: {url}")
            return url
    except Exception as e:
        logger.error(f"Erro ao criar projecto no Notion: {e}")
        return ""

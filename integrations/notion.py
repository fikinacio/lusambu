import logging
import os
from datetime import date

import httpx

logger = logging.getLogger(__name__)

NOTION_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('NOTION_API_KEY', '')}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _text_block(content: str, type_: str = "paragraph") -> dict:
    return {
        "object": "block",
        "type": type_,
        type_: {"rich_text": [{"type": "text", "text": {"content": content}}]},
    }


def _heading(content: str, level: int = 2) -> dict:
    type_ = f"heading_{level}"
    return {
        "object": "block",
        "type": type_,
        type_: {"rich_text": [{"type": "text", "text": {"content": content}}]},
    }


async def create_project_page(project_data: dict) -> str:
    """Cria página do projecto na base de dados Notion. Devolve page_id."""
    database_id = os.getenv("NOTION_DATABASE_ID", "")
    empresa = project_data.get("empresa", "Cliente")
    servico = project_data.get("servico_tipo", "Projecto")
    title = f"{empresa} — {servico}"

    milestone_blocks = [
        _text_block(
            f"{m['ordem']}. {m['nome']} — previsto: {m.get('data_prevista', '—')} | pendente",
            "bulleted_list_item",
        )
        for m in project_data.get("milestones", [])
    ]

    children = [
        _heading("Informações do Projecto"),
        _text_block(f"Cliente: {empresa}", "bulleted_list_item"),
        _text_block(f"Contacto: {project_data.get('contact_name', '—')}", "bulleted_list_item"),
        _text_block(f"Canal: {project_data.get('canal_preferido', 'whatsapp')}", "bulleted_list_item"),
        _text_block(f"Email: {project_data.get('email', '—')}", "bulleted_list_item"),
        _text_block(f"Serviço: {servico}", "bulleted_list_item"),
        _text_block(f"Valor: {project_data.get('valor', '—')}", "bulleted_list_item"),
        _text_block(f"Início: {project_data.get('data_inicio', '—')}", "bulleted_list_item"),
        _text_block(f"Prazo: {project_data.get('prazo_estimado', '—')}", "bulleted_list_item"),
        _text_block("Status: Em Curso", "bulleted_list_item"),
        _heading("Milestones"),
        *milestone_blocks,
        _heading("Comunicações com Cliente"),
        _heading("Ficheiros e Entregas"),
        _heading("Notas Internas"),
    ]

    page = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
        },
        "children": children,
    }

    async with httpx.AsyncClient(timeout=15, base_url=NOTION_URL) as client:
        try:
            r = await client.post("/pages", json=page, headers=_headers())
            r.raise_for_status()
            page_id = r.json()["id"]
            logger.info(f"Página Notion criada: {page_id} ({title})")
            return page_id
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao criar página Notion: {e.response.status_code}")
            raise


async def update_project_page_status(page_id: str, status: str) -> bool:
    """Actualiza a propriedade Status da página Notion."""
    async with httpx.AsyncClient(timeout=15, base_url=NOTION_URL) as client:
        try:
            r = await client.patch(
                f"/pages/{page_id}",
                json={"properties": {"Status": {"select": {"name": status}}}},
                headers=_headers(),
            )
            r.raise_for_status()
            logger.info(f"Página Notion {page_id} status → {status}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao actualizar Notion {page_id}: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Erro ao actualizar Notion {page_id}: {e}")
            return False


async def add_communication_log(page_id: str, message: str) -> bool:
    """Adiciona linha de registo de comunicação à página Notion."""
    entry = f"[{date.today().isoformat()}] {message}"
    async with httpx.AsyncClient(timeout=15, base_url=NOTION_URL) as client:
        try:
            r = await client.patch(
                f"/blocks/{page_id}/children",
                json={"children": [_text_block(entry, "bulleted_list_item")]},
                headers=_headers(),
            )
            r.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao registar log Notion {page_id}: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Erro ao registar log Notion {page_id}: {e}")
            return False


async def add_milestone_update(page_id: str, milestone_nome: str, status: str) -> bool:
    """Adiciona nota de actualização de milestone à página Notion."""
    entry = f"[{date.today().isoformat()}] Milestone: {milestone_nome} → {status}"
    async with httpx.AsyncClient(timeout=15, base_url=NOTION_URL) as client:
        try:
            r = await client.patch(
                f"/blocks/{page_id}/children",
                json={"children": [_text_block(entry, "bulleted_list_item")]},
                headers=_headers(),
            )
            r.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao actualizar milestone Notion {page_id}: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Erro ao actualizar milestone Notion {page_id}: {e}")
            return False

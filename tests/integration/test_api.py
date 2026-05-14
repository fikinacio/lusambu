"""
Integração: endpoints FastAPI.
Usa httpx.AsyncClient com ASGITransport — sem servidor real.
O grafo e o Redis são mockados para não precisar de infra.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langgraph.checkpoint.memory import MemorySaver

import httpx
from httpx import ASGITransport


def _payload_valido(numero: str, texto: str, from_me: bool = False) -> dict:
    return {
        "data": {
            "key": {"fromMe": from_me, "remoteJid": f"{numero}@s.whatsapp.net"},
            "message": {"conversation": texto},
        }
    }


@pytest.fixture
async def client():
    """
    Cliente de teste com o grafo completamente mockado.
    Não toca no Redis nem no LLM — testa apenas o comportamento do endpoint.
    """
    with patch("agent.graph.AsyncRedisSaver") as mock_redis, \
         patch("agent.nodes.llm"), \
         patch("agent.nodes.llm_extractor"), \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        mock_redis.from_conn_string.return_value = MemorySaver()

        from main import app
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "agent": "Lusambu"}


# ---------------------------------------------------------------------------
# /webhook/lusambu — respostas imediatas
# ---------------------------------------------------------------------------

async def test_webhook_mensagem_valida_retorna_processing(client):
    """Mensagem válida → 200 com status processing (processamento é async)."""
    response = await client.post(
        "/webhook/lusambu",
        json=_payload_valido("244923111111", "Olá, vi o anúncio"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


async def test_webhook_mensagem_do_bot_retorna_ignored(client):
    """Mensagem enviada pelo próprio bot → 200 com status ignored."""
    response = await client.post(
        "/webhook/lusambu",
        json=_payload_valido("244923111111", "Mensagem do bot", from_me=True),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_webhook_sem_texto_retorna_ignored(client):
    """Payload sem texto (ex: imagem, áudio) → ignored."""
    payload = {
        "data": {
            "key": {"fromMe": False, "remoteJid": "244923111111@s.whatsapp.net"},
            "message": {"imageMessage": {}},
        }
    }
    response = await client.post("/webhook/lusambu", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_webhook_payload_invalido_retorna_400(client):
    """Payload que não é JSON válido → 400."""
    response = await client.post(
        "/webhook/lusambu",
        content=b"isto nao e json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


async def test_webhook_payload_vazio_retorna_ignored(client):
    """Payload JSON vazio → ignored (não é erro, apenas sem dados úteis)."""
    response = await client.post("/webhook/lusambu", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"

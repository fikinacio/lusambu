import os
import logging
import httpx

logger = logging.getLogger(__name__)

EVOLUTION_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
FIDEL_NUMBER = os.getenv("FIDEL_WHATSAPP_NUMBER", "")


async def send_whatsapp_message(number: str, text: str) -> bool:
    """Envia mensagem de texto via Evolution API."""
    url = f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    payload = {"number": number, "text": text}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            logger.info(f"Mensagem enviada para {number}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP ao enviar para {number}: {e.response.status_code} — {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para {number}: {e}")
        return False


async def notify_fidel(message: str) -> bool:
    """Envia notificação para o número do Fidel."""
    if not FIDEL_NUMBER:
        logger.warning("FIDEL_WHATSAPP_NUMBER não configurado.")
        return False
    return await send_whatsapp_message(FIDEL_NUMBER, message)

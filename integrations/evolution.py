import os
import logging
import httpx

logger = logging.getLogger(__name__)

EVOLUTION_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
FIDEL_NUMBER = os.getenv("FIDEL_WHATSAPP", "")


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


async def send_typing_indicator(number: str) -> None:
    """Envia sinal 'a escrever...' via Evolution API. Falha silenciosamente."""
    url = f"{EVOLUTION_URL}/chat/sendPresence/{EVOLUTION_INSTANCE}"
    payload = {"number": number, "options": {"presence": "composing"}}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                url,
                headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
                json=payload,
            )
    except Exception:
        pass  # typing indicator é best-effort — nunca bloqueia o fluxo


async def notify_fidel(message: str) -> bool:
    """Envia notificação para o número do Fidel."""
    if not FIDEL_NUMBER:
        logger.warning("FIDEL_WHATSAPP_NUMBER não configurado.")
        return False
    return await send_whatsapp_message(FIDEL_NUMBER, message)


async def send_button_message(
    number: str,
    body_text: str,
    buttons: list[dict],
    footer: str = "",
) -> bool:
    """Envia mensagem com botões interactivos via Evolution API."""
    url = f"{EVOLUTION_URL}/message/sendButtons/{EVOLUTION_INSTANCE}"
    payload = {
        "number": number,
        "buttonMessage": {
            "text": body_text,
            "footer": footer,
            "buttons": buttons,
            "headerType": 1,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            logger.info(f"Botões enviados para {number}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP ao enviar botões para {number}: {e.response.status_code} — {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Erro ao enviar botões para {number}: {e}")
        return False


async def send_media_message(
    number: str,
    media_url: str,
    mediatype: str = "image",
    caption: str = "",
) -> bool:
    """Envia imagem ou ficheiro via Evolution API."""
    url = f"{EVOLUTION_URL}/message/sendMedia/{EVOLUTION_INSTANCE}"
    payload = {
        "number": number,
        "mediatype": mediatype,
        "media": media_url,
        "caption": caption,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            logger.info(f"Media enviada para {number}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP ao enviar media para {number}: {e.response.status_code} — {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Erro ao enviar media para {number}: {e}")
        return False

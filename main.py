import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from langchain_core.messages import HumanMessage

from config import settings
from agent import create_graph, LusambuState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    graph = create_graph(settings.REDIS_URL)
    logger.info("Lusambu iniciado e pronto.")
    yield
    logger.info("Lusambu encerrado.")


app = FastAPI(title="Lusambu — Agente de Vendas Bisca+", lifespan=lifespan)


def _parse_evolution_webhook(data: dict) -> tuple[str, str] | tuple[None, None]:
    """
    Extrai número e texto da payload da Evolution API.
    Retorna (None, None) se a mensagem não for para processar.
    """
    try:
        msg_data = data.get("data", {})

        # Ignora mensagens enviadas pelo próprio bot
        if msg_data.get("key", {}).get("fromMe"):
            return None, None

        number = msg_data.get("key", {}).get("remoteJid", "")
        number = number.replace("@s.whatsapp.net", "").replace("@g.us", "")

        # Suporta texto simples e mensagem extendida
        message_obj = msg_data.get("message", {})
        text = (
            message_obj.get("conversation")
            or message_obj.get("extendedTextMessage", {}).get("text")
            or ""
        )

        if not number or not text:
            return None, None

        return number, text.strip()

    except Exception as e:
        logger.error(f"Erro ao parsear webhook: {e}")
        return None, None


async def _process_message(number: str, text: str):
    """
    Processa mensagem de forma assíncrona — não bloqueia o webhook.

    Para conversas existentes, passa apenas a nova mensagem — o checkpointer
    Redis carrega o estado anterior (stage, lead_info, objection_count, etc.)
    sem os repor a zero.
    Para conversas novas, passa o estado inicial completo.
    """
    config = {"configurable": {"thread_id": number}}

    existing = await graph.aget_state(config)

    if existing.values:
        # Conversa existente — o checkpointer carrega o estado; só adicionamos a nova mensagem
        input_state = {"messages": [HumanMessage(content=text)]}
    else:
        # Primeira mensagem deste número — estado inicial completo
        input_state: LusambuState = {
            "messages": [HumanMessage(content=text)],
            "whatsapp_number": number,
            "lead_info": {},
            "stage": "qualify",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
        }

    try:
        await graph.ainvoke(input_state, config=config)
    except Exception as e:
        logger.error(f"Erro ao processar mensagem de {number}: {e}")


@app.post("/webhook/lusambu")
async def webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido")

    number, text = _parse_evolution_webhook(data)

    if not number or not text:
        return {"status": "ignored"}

    logger.info(f"Mensagem recebida de {number}: {text[:50]}...")

    # Processa em background para não bloquear a resposta ao Evolution
    asyncio.create_task(_process_message(number, text))

    return {"status": "processing"}


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "Lusambu"}

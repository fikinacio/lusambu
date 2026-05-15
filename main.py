import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

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
    os.makedirs(os.path.dirname(settings.CHECKPOINT_DB_PATH), exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(settings.CHECKPOINT_DB_PATH) as checkpointer:
        graph = create_graph(checkpointer)
        logger.info(f"Lusambu iniciado. Checkpoints em {settings.CHECKPOINT_DB_PATH}")
        yield
    logger.info("Lusambu encerrado.")


app = FastAPI(title="Lusambu — Agente de Vendas Bisca+", lifespan=lifespan)


def _parse_evolution_webhook(data: dict) -> tuple[str, str] | tuple[None, None]:
    try:
        msg_data = data.get("data", {})

        if msg_data.get("key", {}).get("fromMe"):
            return None, None

        number = msg_data.get("key", {}).get("remoteJid", "")
        number = number.replace("@s.whatsapp.net", "").replace("@g.us", "")

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
    config = {"configurable": {"thread_id": number}}

    existing = await graph.aget_state(config)

    if existing.values:
        input_state = {"messages": [HumanMessage(content=text)]}
    else:
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

    asyncio.create_task(_process_message(number, text))

    return {"status": "processing"}


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "Lusambu"}

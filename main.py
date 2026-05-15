import asyncio
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config import settings
from agent import create_graph, LusambuState
from integrations.evolution import send_whatsapp_message
from integrations.supabase_client import get_stale_leads, increment_followup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

graph = None

_FOLLOWUP_MSGS = {
    "qualify": "Olá! Percebo que és ocupado. Tens 2 minutos para continuar a nossa conversa?",
    "pitch":   "Só a verificar — ficaste com alguma dúvida sobre o que te partilhei?",
    "objection": "Ainda estás a pensar? Posso esclarecer alguma coisa específica.",
}
_FOLLOWUP_DEFAULT = "Olá! Queria só confirmar se ainda tens interesse em perceber como podemos ajudar o teu negócio."


async def _send_followups() -> None:
    """Envia follow-up a leads que não responderam em 24h."""
    leads = await get_stale_leads(hours=24)
    if not leads:
        return
    logger.info(f"Follow-up: {len(leads)} lead(s) a contactar.")
    for lead in leads:
        number = lead.get("whatsapp")
        stage = lead.get("stage", "qualify")
        msg = _FOLLOWUP_MSGS.get(stage, _FOLLOWUP_DEFAULT)
        try:
            await send_whatsapp_message(number, msg)
            await increment_followup(number)
            logger.info(f"Follow-up enviado para {number}")
        except Exception as e:
            logger.error(f"Erro ao enviar follow-up para {number}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    os.makedirs(os.path.dirname(settings.CHECKPOINT_DB_PATH), exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(settings.CHECKPOINT_DB_PATH) as checkpointer:
        graph = create_graph(checkpointer)
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_send_followups, "interval", hours=1, id="followup")
        scheduler.start()
        logger.info(f"Lusambu iniciado. Checkpoints em {settings.CHECKPOINT_DB_PATH}")
        yield
        scheduler.shutdown(wait=False)
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


def _fresh_state(number: str, text: str) -> LusambuState:
    return {
        "messages": [HumanMessage(content=text)],
        "whatsapp_number": number,
        "lead_info": {},
        "stage": "qualify",
        "objection_count": 0,
        "turn_count": 0,
        "escalation_reason": "",
        "fidel_notified": False,
    }


async def _process_message(number: str, text: str):
    config = {"configurable": {"thread_id": number}}

    existing = await graph.aget_state(config)
    existing_stage = existing.values.get("stage") if existing.values else None

    if existing_stage == "end":
        # Lead voltou após conversa terminada — reinicia completamente
        logger.info(f"Re-entry de {number} (stage anterior: end)")
        input_state = _fresh_state(number, text)
    elif existing.values:
        input_state = {"messages": [HumanMessage(content=text)]}
    else:
        input_state = _fresh_state(number, text)

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

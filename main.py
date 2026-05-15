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
from fastapi.responses import HTMLResponse
from integrations.evolution import send_whatsapp_message
from integrations.supabase_client import get_stale_leads, increment_followup, get_all_leads

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


def _badge(value: str, mapping: dict, default: str = "#888") -> str:
    color = mapping.get((value or "").lower(), default)
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px">{value or "—"}</span>'


_CLS_COLORS  = {"hot": "#e53935", "warm": "#fb8c00", "cold": "#1e88e5", "unknown": "#888"}
_STG_COLORS  = {"escalado": "#7b1fa2", "descartado": "#616161", "qualify": "#00897b",
                "pitch": "#1565c0", "objection": "#f57f17", "end": "#616161"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(key: str = ""):
    if settings.DASHBOARD_KEY and key != settings.DASHBOARD_KEY:
        raise HTTPException(status_code=403, detail="Chave inválida")

    leads = await get_all_leads()
    total = len(leads)
    hot   = sum(1 for l in leads if (l.get("classification") or "").lower() == "hot")
    warm  = sum(1 for l in leads if (l.get("classification") or "").lower() == "warm")
    esc   = sum(1 for l in leads if (l.get("status") or "").lower() == "escalado")

    rows = ""
    for l in leads:
        last = (l.get("last_contact_at") or "")[:16].replace("T", " ")
        rows += f"""
        <tr>
          <td>{l.get("name") or "—"}</td>
          <td>{l.get("company") or "—"}</td>
          <td>{l.get("sector") or "—"}</td>
          <td>{_badge(l.get("classification"), _CLS_COLORS)}</td>
          <td>{_badge(l.get("status") or l.get("stage"), _STG_COLORS)}</td>
          <td style="font-size:12px;color:#aaa">{l.get("pain_point") or "—"}</td>
          <td style="font-size:12px">{l.get("whatsapp") or "—"}</td>
          <td style="font-size:12px;color:#aaa">{last}</td>
          <td style="text-align:center">{l.get("followup_count") or 0}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lusambu — Leads</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0;margin:0;padding:24px}}
  h1{{color:#fff;margin-bottom:4px}}
  .sub{{color:#888;font-size:14px;margin-bottom:24px}}
  .stats{{display:flex;gap:16px;margin-bottom:24px}}
  .stat{{background:#1e1e1e;border-radius:10px;padding:16px 24px;min-width:100px}}
  .stat .n{{font-size:28px;font-weight:700;color:#fff}}
  .stat .l{{font-size:12px;color:#888}}
  table{{width:100%;border-collapse:collapse;background:#1e1e1e;border-radius:10px;overflow:hidden}}
  th{{background:#2a2a2a;padding:10px 14px;text-align:left;font-size:12px;color:#aaa;font-weight:600}}
  td{{padding:10px 14px;border-bottom:1px solid #2a2a2a;vertical-align:middle}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:#252525}}
</style>
</head><body>
<h1>🤖 Lusambu — Pipeline de Leads</h1>
<p class="sub">Actualiza ao recarregar a página</p>
<div class="stats">
  <div class="stat"><div class="n">{total}</div><div class="l">Total</div></div>
  <div class="stat"><div class="n" style="color:#e53935">{hot}</div><div class="l">Hot 🔥</div></div>
  <div class="stat"><div class="n" style="color:#fb8c00">{warm}</div><div class="l">Warm 🟡</div></div>
  <div class="stat"><div class="n" style="color:#7b1fa2">{esc}</div><div class="l">Escalados</div></div>
</div>
<table>
  <thead><tr>
    <th>Nome</th><th>Empresa</th><th>Sector</th><th>Class.</th>
    <th>Stage</th><th>Dor</th><th>WhatsApp</th><th>Último contacto</th><th>Follow-ups</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
</body></html>"""
    return HTMLResponse(content=html)

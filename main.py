import asyncio
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
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
        # Remove device ID presente em contas multi-device / Meta-linked
        # Ex: "244923456789:7" → "244923456789"
        number = number.split(":")[0]

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


def _fresh_state(number: str, text: str, message_offset: int = 0) -> LusambuState:
    return {
        "messages": [HumanMessage(content=text)],
        "whatsapp_number": number,
        "lead_info": {},
        "stage": "qualify",
        "objection_count": 0,
        "turn_count": 0,
        "message_offset": message_offset,
        "prompt_variant": "",
        "escalation_reason": "",
        "fidel_notified": False,
        "data_confirmed": False,
        "calendly_sent": False,
        "supervisor_decision": {},
        "sales_agent_active": False,
        "outreach_message": None,
        "outreach_source": "",
    }


async def _process_message(number: str, text: str):
    config = {"configurable": {"thread_id": number}}

    existing = await graph.aget_state(config)
    existing_stage = existing.values.get("stage") if existing.values else None

    if existing_stage == "end":
        # Lead voltou após conversa terminada — reinicia com offset para ignorar histórico antigo
        offset = len(existing.values.get("messages", []))
        logger.info(f"Re-entry de {number} — offset={offset}")
        input_state = _fresh_state(number, text, message_offset=offset)
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
    label = (value or "—").upper()
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px">{label}</span>'


_CLS_COLORS = {"hot": "#e53935", "warm": "#fb8c00", "cold": "#1e88e5", "unknown": "#888"}
_STG_COLORS = {"escalado": "#7b1fa2", "descartado": "#616161", "qualify": "#00897b",
               "pitch": "#1565c0", "objection": "#f57f17", "end": "#616161"}


def _build_stats_and_rows(leads: list[dict]) -> dict:
    total = len(leads)
    hot   = sum(1 for l in leads if (l.get("classification") or "").lower() == "hot")
    warm  = sum(1 for l in leads if (l.get("classification") or "").lower() == "warm")
    esc   = sum(1 for l in leads if (l.get("status") or "").lower() == "escalado")
    return {"total": total, "hot": hot, "warm": warm, "escalados": esc, "leads": leads}


@app.get("/dashboard/data")
async def dashboard_data(key: str = ""):
    if settings.DASHBOARD_KEY and key != settings.DASHBOARD_KEY:
        raise HTTPException(status_code=403, detail="Chave inválida")
    leads = await get_all_leads()
    return JSONResponse(_build_stats_and_rows(leads))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(key: str = ""):
    if settings.DASHBOARD_KEY and key != settings.DASHBOARD_KEY:
        raise HTTPException(status_code=403, detail="Chave inválida")

    key_param = f"?key={key}" if key else ""

    html = f"""<!DOCTYPE html>
<html lang="pt"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lusambu — Leads</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0;margin:0;padding:24px}}
  h1{{color:#fff;margin-bottom:4px}}
  .sub{{color:#888;font-size:13px;margin-bottom:24px;display:flex;align-items:center;gap:10px}}
  .dot{{width:8px;height:8px;border-radius:50%;background:#4caf50;display:inline-block;animation:pulse 2s infinite}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
  .stats{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
  .stat{{background:#1e1e1e;border-radius:10px;padding:16px 24px;min-width:100px}}
  .stat .n{{font-size:28px;font-weight:700;color:#fff}}
  .stat .l{{font-size:12px;color:#888}}
  table{{width:100%;border-collapse:collapse;background:#1e1e1e;border-radius:10px;overflow:hidden}}
  th{{background:#2a2a2a;padding:10px 14px;text-align:left;font-size:12px;color:#aaa;font-weight:600}}
  td{{padding:10px 14px;border-bottom:1px solid #2a2a2a;vertical-align:middle}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:#252525}}
  .empty{{text-align:center;padding:40px;color:#555}}
</style>
</head><body>
<h1>🤖 Lusambu — Pipeline de Leads</h1>
<div class="sub">
  <span class="dot"></span>
  <span id="status">A carregar...</span>
</div>
<div class="stats">
  <div class="stat"><div class="n" id="s-total">—</div><div class="l">Total</div></div>
  <div class="stat"><div class="n" id="s-hot" style="color:#e53935">—</div><div class="l">Hot 🔥</div></div>
  <div class="stat"><div class="n" id="s-warm" style="color:#fb8c00">—</div><div class="l">Warm 🟡</div></div>
  <div class="stat"><div class="n" id="s-esc" style="color:#7b1fa2">—</div><div class="l">Escalados</div></div>
</div>
<table>
  <thead><tr>
    <th>Nome</th><th>Empresa</th><th>Sector</th><th>Class.</th>
    <th>Stage</th><th>Dor</th><th>WhatsApp</th><th>Último contacto</th><th>Follow-ups</th><th>Variante</th>
  </tr></thead>
  <tbody id="leads-body"><tr><td colspan="10" class="empty">A carregar leads...</td></tr></tbody>
</table>

<script>
const CLS = {{hot:"#e53935",warm:"#fb8c00",cold:"#1e88e5",unknown:"#888"}};
const STG = {{escalado:"#7b1fa2",descartado:"#616161",qualify:"#00897b",pitch:"#1565c0",objection:"#f57f17",end:"#616161"}};

function badge(val, map) {{
  const v = (val||"").toLowerCase();
  const color = map[v] || "#888";
  return `<span style="background:${{color}};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px">${{(val||"—").toUpperCase()}}</span>`;
}}

function ts(iso) {{
  if (!iso) return "—";
  return iso.slice(0,16).replace("T"," ");
}}

async function refresh() {{
  try {{
    const r = await fetch("/dashboard/data{key_param}");
    if (!r.ok) {{ document.getElementById("status").textContent = "Erro ao carregar (" + r.status + ")"; return; }}
    const d = await r.json();

    document.getElementById("s-total").textContent = d.total;
    document.getElementById("s-hot").textContent   = d.hot;
    document.getElementById("s-warm").textContent  = d.warm;
    document.getElementById("s-esc").textContent   = d.escalados;

    const tbody = document.getElementById("leads-body");
    if (!d.leads || d.leads.length === 0) {{
      tbody.innerHTML = '<tr><td colspan="10" class="empty">Nenhum lead ainda.</td></tr>';
    }} else {{
      tbody.innerHTML = d.leads.map(l => `
        <tr>
          <td>${{l.name||"—"}}</td>
          <td>${{l.company||"—"}}</td>
          <td>${{l.sector||"—"}}</td>
          <td>${{badge(l.classification, CLS)}}</td>
          <td>${{badge(l.status||l.stage, STG)}}</td>
          <td style="font-size:12px;color:#aaa">${{l.pain_point||"—"}}</td>
          <td style="font-size:12px">${{l.whatsapp||"—"}}</td>
          <td style="font-size:12px;color:#aaa">${{ts(l.last_contact_at)}}</td>
          <td style="text-align:center">${{l.followup_count||0}}</td>
          <td style="text-align:center;font-weight:700">${{l.prompt_variant||"—"}}</td>
        </tr>`).join("");
    }}

    const now = new Date().toLocaleTimeString("pt-PT");
    document.getElementById("status").textContent = "Actualizado às " + now + " · próxima actualização em 30s";
  }} catch(e) {{
    document.getElementById("status").textContent = "Erro de rede — a tentar novamente...";
  }}
}}

refresh();
setInterval(refresh, 30000);
</script>
</body></html>"""
    return HTMLResponse(content=html)

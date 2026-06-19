import asyncio
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from config import settings
from agent import create_graph, LusambuState
from proposal_agent import create_proposal_graph
from invoice_agent import create_invoice_graph
from project_agent import create_project_graph
from fastapi.responses import HTMLResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from integrations.evolution import send_whatsapp_message
from integrations.invoiceninja import send_invoice_reminder
from integrations.notion import add_communication_log as notion_add_log, update_project_page_status
from integrations.supabase_client import (
    get_stale_leads, increment_followup, get_all_leads,
    get_outbound_stale_leads, upsert_lead,
    get_pending_proposal_for_fidel,
    update_invoice_draft, get_pending_invoice_for_fidel, get_overdue_invoices,
    update_project, get_draft_project_for_fidel, update_milestone,
    get_delayed_milestones, get_completed_milestones_pending_confirmation,
    get_project_milestones, save_project_event,
    get_pending_project_event_for_fidel, update_project_event,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

graph = None
proposal_graph = None
invoice_graph = None
project_graph = None
FIDEL_NUMBER = os.getenv("FIDEL_WHATSAPP", "")
_llm_followup = ChatAnthropic(model="claude-haiku-3-5", max_tokens=120, temperature=0.7)

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


_FOLLOWUP2_MSG = (
    "Percebo que o momento pode não ser o ideal. "
    "Fico disponível quando fizer sentido. 🙏"
)


async def _send_outbound_followups() -> None:
    """Gere o ciclo de follow-up para leads outbound (status='enviado')."""
    # --- Passo 1: Follow-up 1 (48h, LLM) ---
    leads1 = await get_outbound_stale_leads(followup_count=0, hours=48)
    for lead in leads1:
        number = lead.get("whatsapp")
        try:
            prompt = (
                f"Gera uma mensagem curta de follow-up para um lead de prospecção.\n"
                f"Nome: {lead.get('name') or 'o contacto'}\n"
                f"Sector: {lead.get('sector') or 'desconhecido'}\n"
                f"Dor identificada: {lead.get('pain_point') or 'não identificada'}\n\n"
                "Regras:\n"
                "- Ângulo novo, não repitas a mensagem inicial\n"
                "- Máximo 3 linhas\n"
                "- Português europeu, directo, sem linguagem de chatbot\n"
                "- Não uses listas nem emojis excessivos\n"
                "Devolve apenas o texto da mensagem, sem aspas nem prefixos."
            )
            response = await _llm_followup.ainvoke([SystemMessage(content=prompt)])
            msg = response.content.strip()
            await send_whatsapp_message(number, msg)
            await increment_followup(number)
            logger.info(f"Outbound follow-up 1 enviado para {number}")
        except Exception as e:
            logger.error(f"Erro ao enviar outbound follow-up 1 para {number}: {e}")

    # --- Passo 2: Follow-up 2 (72h após follow-up 1, fixo) ---
    leads2 = await get_outbound_stale_leads(followup_count=1, hours=72)
    for lead in leads2:
        number = lead.get("whatsapp")
        try:
            await send_whatsapp_message(number, _FOLLOWUP2_MSG)
            await increment_followup(number)
            logger.info(f"Outbound follow-up 2 enviado para {number}")
        except Exception as e:
            logger.error(f"Erro ao enviar outbound follow-up 2 para {number}: {e}")

    # --- Passo 3: Marcar sem_resposta (48h após follow-up 2) ---
    leads3 = await get_outbound_stale_leads(followup_count=2, hours=48)
    for lead in leads3:
        number = lead.get("whatsapp")
        try:
            await upsert_lead({"whatsapp": number, "status": "sem_resposta"})
            logger.info(f"Lead {number} marcado como sem_resposta")
        except Exception as e:
            logger.error(f"Erro ao marcar sem_resposta para {number}: {e}")


async def _run_project(whatsapp: str) -> None:
    """Inicia o grafo de gestão de projecto para um lead."""
    config = {"configurable": {"thread_id": f"project-{whatsapp}"}}
    try:
        await project_graph.ainvoke({"whatsapp": whatsapp}, config=config)
    except Exception as e:
        logger.error(f"Erro ao iniciar projecto para {whatsapp}: {e}")


async def _handle_project_event_response(event: dict, fidel_message: str) -> None:
    """Processa confirmação do Fidel para milestone concluído ou conclusão de projecto."""
    confirmed = any(w in fidel_message.lower() for w in ["sim", "ok", "confirm", "1", "✅", "aprov"])
    if not confirmed:
        await update_project_event(event["id"], {"status": "dismissed"})
        return

    whatsapp = event.get("whatsapp", "")
    notion_page_id = event.get("notion_page_id", "")

    if event["event_type"] == "milestone_done":
        milestone_nome = event.get("event_data", {}).get("milestone_nome", "milestone")
        nome = event.get("contact_name") or event.get("empresa", "")
        msg = f"Olá {nome}! O milestone *{milestone_nome}* foi concluído com sucesso. 🎉"
        await send_whatsapp_message(whatsapp, msg)
        if notion_page_id:
            await notion_add_log(notion_page_id, f"Cliente notificado: {milestone_nome} concluído.")
        await update_project_event(event["id"], {"status": "confirmed"})

    elif event["event_type"] == "completion":
        nome = event.get("contact_name") or event.get("empresa", "")
        msg = (
            f"Olá {nome}!\n\n"
            "O projecto foi concluído com sucesso. 🎉\n\n"
            "Foi um prazer trabalhar convosco. Estamos disponíveis para qualquer suporte.\n\n"
            "Fidel Kussunga | Bisca+"
        )
        await send_whatsapp_message(whatsapp, msg)
        project_id = event.get("project_id", "")
        if project_id:
            from datetime import date
            await update_project(project_id, {"status": "concluido", "data_inicio": date.today().isoformat()})
        if notion_page_id:
            await update_project_page_status(notion_page_id, "Concluído")
            await notion_add_log(notion_page_id, "Projecto concluído. Cliente notificado.")
        await update_project_event(event["id"], {"status": "confirmed"})


async def _resume_project_for_fidel(fidel_message: str) -> None:
    """Retoma evento de projecto ou grafo de arranque com a decisão do Fidel."""
    event = await get_pending_project_event_for_fidel()
    if event:
        await _handle_project_event_response(event, fidel_message)
        return
    project = await get_draft_project_for_fidel()
    if project:
        whatsapp = project.get("whatsapp", "")
        config = {"configurable": {"thread_id": f"project-{whatsapp}"}}
        try:
            await project_graph.ainvoke(Command(resume=fidel_message), config=config)
        except Exception as e:
            logger.error(f"Erro ao retomar projecto para {whatsapp}: {e}")
        return
    logger.warning("Fidel respondeu mas não há evento de projecto pendente.")


async def _check_project_events() -> None:
    """Verifica milestones atrasados, concluídos e projectos prontos a fechar."""
    # 1. Milestones atrasados → alerta ao Fidel
    delayed = await get_delayed_milestones()
    for m in delayed:
        try:
            empresa = m.get("empresa", "cliente")
            msg = f"⚠️ Milestone atrasado em *{empresa}*: _{m['nome']}_ (previsto: {m.get('data_prevista', '—')})."
            await send_whatsapp_message(FIDEL_NUMBER, msg)
            await update_milestone(m["id"], {"status": "atrasado"})
            logger.info(f"Alerta de milestone atrasado enviado: {m['id']}")
        except Exception as e:
            logger.error(f"Erro ao alertar milestone atrasado {m.get('id')}: {e}")

    # 2. Milestones concluídos aguardando confirmação do Fidel → pede confirmação
    completed = await get_completed_milestones_pending_confirmation()
    for m in completed:
        try:
            from integrations.evolution import send_button_message
            empresa = m.get("empresa", "cliente")
            milestone_nome = m.get("nome", "milestone")
            msg = f"✅ Milestone concluído em *{empresa}*: _{milestone_nome}_\nNotificar o cliente?"
            await send_button_message(
                number=FIDEL_NUMBER,
                body_text=msg,
                buttons=[
                    {"buttonId": "sim", "buttonText": {"displayText": "✅ Sim, notificar"}},
                    {"buttonId": "nao", "buttonText": {"displayText": "❌ Não agora"}},
                ],
            )
            await save_project_event({
                "project_id": m["project_id"],
                "event_type": "milestone_done",
                "milestone_id": m["id"],
                "event_data": {"milestone_nome": milestone_nome},
                "status": "pending",
            })
            await update_milestone(m["id"], {"fidel_alerted_completion": True})
            logger.info(f"Confirmação de milestone enviada ao Fidel: {m['id']}")
        except Exception as e:
            logger.error(f"Erro ao pedir confirmação de milestone {m.get('id')}: {e}")

    # 3. Projectos com todos milestones concluídos → pede validação final
    from integrations.evolution import send_button_message as _sbm
    from integrations.supabase_client import get_project_by_whatsapp as _gpbw
    try:
        from supabase import Client
        db_projects = (
            __import__("integrations.supabase_client", fromlist=["get_supabase"]).get_supabase()
            .table("projects")
            .select("id, whatsapp, empresa")
            .eq("status", "em_curso")
            .execute()
        )
        for proj in (db_projects.data or []):
            milestones = await get_project_milestones(proj["id"])
            if milestones and all(m.get("status") == "concluido" for m in milestones):
                existing = await get_pending_project_event_for_fidel()
                if existing and existing.get("project_id") == proj["id"]:
                    continue
                msg = f"🏁 Todos os milestones de *{proj['empresa']}* estão concluídos. Validar e fechar projecto?"
                await _sbm(
                    number=FIDEL_NUMBER,
                    body_text=msg,
                    buttons=[
                        {"buttonId": "sim", "buttonText": {"displayText": "✅ Confirmar conclusão"}},
                        {"buttonId": "nao", "buttonText": {"displayText": "❌ Ainda não"}},
                    ],
                )
                await save_project_event({
                    "project_id": proj["id"],
                    "event_type": "completion",
                    "status": "pending",
                })
                logger.info(f"Pedido de conclusão enviado ao Fidel para projecto {proj['id']}")
    except Exception as e:
        logger.error(f"Erro ao verificar conclusão de projectos: {e}")


async def _run_invoice(whatsapp: str) -> None:
    """Inicia o grafo de factura para um lead."""
    config = {"configurable": {"thread_id": f"invoice-{whatsapp}"}}
    try:
        await invoice_graph.ainvoke({"whatsapp": whatsapp}, config=config)
    except Exception as e:
        logger.error(f"Erro ao iniciar factura para {whatsapp}: {e}")


async def _resume_invoice_for_fidel(fidel_message: str) -> None:
    """Retoma o grafo de factura pausado com a decisão do Fidel."""
    draft = await get_pending_invoice_for_fidel()
    if not draft:
        logger.warning("Fidel respondeu mas não há factura pendente.")
        return
    whatsapp = draft.get("whatsapp", "")
    config = {"configurable": {"thread_id": f"invoice-{whatsapp}"}}
    try:
        await invoice_graph.ainvoke(Command(resume=fidel_message), config=config)
    except Exception as e:
        logger.error(f"Erro ao retomar factura para {whatsapp}: {e}")


async def _route_fidel_message(text: str) -> None:
    """Determina se Fidel está a responder a uma proposta, factura ou evento de projecto."""
    if await get_pending_proposal_for_fidel():
        await _resume_proposal_for_fidel(text)
        return
    if await get_pending_project_event_for_fidel() or await get_draft_project_for_fidel():
        await _resume_project_for_fidel(text)
        return
    if await get_pending_invoice_for_fidel():
        await _resume_invoice_for_fidel(text)
        return
    logger.warning("Fidel respondeu mas não há proposta, factura ou evento de projecto pendente.")


async def _check_payment_alerts() -> None:
    """Verifica facturas em atraso e envia alertas."""
    # 7 dias sem pagamento → alerta ao Fidel via WhatsApp
    overdue_7d = await get_overdue_invoices(days=7, alerted_field="fidel_alerted_7d")
    for inv in overdue_7d:
        try:
            empresa = inv.get("empresa", "cliente")
            invoice_number = inv.get("invoice_number", "—")
            msg = f"⚠️ A factura para *{empresa}* (Nº {invoice_number}) está por pagar há 7 dias."
            await send_whatsapp_message(FIDEL_NUMBER, msg)
            await update_invoice_draft(inv["id"], {"fidel_alerted_7d": True})
            logger.info(f"Alerta 7d enviado ao Fidel para factura {inv['id']}")
        except Exception as e:
            logger.error(f"Erro ao enviar alerta 7d para factura {inv.get('id')}: {e}")

    # 14 dias sem pagamento → reminder automático ao cliente
    overdue_14d = await get_overdue_invoices(days=14, alerted_field="client_alerted_14d")
    for inv in overdue_14d:
        try:
            await send_invoice_reminder(inv.get("invoice_id", ""))
            await update_invoice_draft(inv["id"], {"client_alerted_14d": True})
            logger.info(f"Reminder 14d enviado ao cliente para factura {inv['id']}")
        except Exception as e:
            logger.error(f"Erro ao enviar reminder 14d para factura {inv.get('id')}: {e}")


async def _run_proposal(whatsapp: str) -> None:
    """Inicia o grafo de proposta para um lead."""
    config = {"configurable": {"thread_id": f"proposal-{whatsapp}"}}
    try:
        await proposal_graph.ainvoke({"whatsapp": whatsapp}, config=config)
    except Exception as e:
        logger.error(f"Erro ao iniciar proposta para {whatsapp}: {e}")


async def _resume_proposal_for_fidel(fidel_message: str) -> None:
    """Retoma o grafo de proposta pausado com a decisão do Fidel."""
    draft = await get_pending_proposal_for_fidel()
    if not draft:
        logger.warning("Fidel respondeu mas não há proposta pendente.")
        return
    whatsapp = draft.get("whatsapp", "")
    config = {"configurable": {"thread_id": f"proposal-{whatsapp}"}}
    try:
        await proposal_graph.ainvoke(Command(resume=fidel_message), config=config)
    except Exception as e:
        logger.error(f"Erro ao retomar proposta para {whatsapp}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, proposal_graph, invoice_graph, project_graph
    os.makedirs(os.path.dirname(settings.CHECKPOINT_DB_PATH), exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(settings.CHECKPOINT_DB_PATH) as checkpointer:
        graph = create_graph(checkpointer)
        proposal_graph = create_proposal_graph(checkpointer)
        invoice_graph = create_invoice_graph(checkpointer)
        project_graph = create_project_graph(checkpointer)
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_send_followups, "interval", hours=1, id="followup")
        scheduler.add_job(_send_outbound_followups, "interval", hours=1, id="outbound_followup")
        scheduler.add_job(_check_payment_alerts, "interval", hours=6, id="payment_alerts")
        scheduler.add_job(_check_project_events, "interval", hours=4, id="project_events")
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
            or message_obj.get("buttonsResponseMessage", {}).get("selectedButtonId")
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
        "prospect": None,
        "historico": [],
    }


async def _process_message(number: str, text: str):
    if FIDEL_NUMBER and number == FIDEL_NUMBER:
        await _route_fidel_message(text)
        return

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


class ProposalRunRequest(BaseModel):
    whatsapp: str


@app.post("/proposal/run")
async def proposal_run(request: ProposalRunRequest):
    asyncio.create_task(_run_proposal(request.whatsapp))
    return {"status": "started", "whatsapp": request.whatsapp}


class InvoiceRunRequest(BaseModel):
    whatsapp: str


@app.post("/invoice/run")
async def invoice_run(request: InvoiceRunRequest):
    asyncio.create_task(_run_invoice(request.whatsapp))
    return {"status": "started", "whatsapp": request.whatsapp}


class ProjectRunRequest(BaseModel):
    whatsapp: str


@app.post("/project/run")
async def project_run(request: ProjectRunRequest):
    asyncio.create_task(_run_project(request.whatsapp))
    return {"status": "started", "whatsapp": request.whatsapp}


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

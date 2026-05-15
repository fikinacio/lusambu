import asyncio
import json
import logging
import random
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage

from .state import LusambuState, LeadInfo
from .prompts import SYSTEM_PROMPT, EXTRACTION_PROMPT
from integrations.evolution import send_whatsapp_message, notify_fidel
from integrations.supabase_client import upsert_lead

logger = logging.getLogger(__name__)

llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=500, temperature=0.7)
llm_extractor = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=300, temperature=0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _human_delay():
    """Simula delay humano (3–8 segundos) antes de enviar mensagem."""
    await asyncio.sleep(random.uniform(3, 8))


async def _extract_lead_info(messages: list) -> LeadInfo:
    """Chama LLM para extrair dados estruturados da conversa."""
    try:
        # A conversa deve terminar com HumanMessage — Claude não suporta prefill de assistente
        extract_msgs = [SystemMessage(content=EXTRACTION_PROMPT)] + list(messages) + [
            HumanMessage(content="Extrai o JSON agora.")
        ]
        response = await llm_extractor.ainvoke(extract_msgs)
        content = response.content.strip()
        # Remove bloco markdown se presente (```json ... ```)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        logger.error(f"Erro ao extrair lead info: {e}")
        return {
            "has_business": None,
            "classification": "unknown",
            "is_objecting": False,
            "wants_human": False,
            "ready_to_close": False,
        }


MAX_TURNS = 12


def _determine_stage(lead_info: LeadInfo, objection_count: int, turn_count: int) -> str:
    """Define o próximo stage com base na informação extraída."""
    if lead_info.get("has_business") is False:
        return "discard"
    if turn_count >= MAX_TURNS:
        return "escalate"
    if lead_info.get("wants_human") or objection_count >= 2:
        return "escalate"
    if lead_info.get("ready_to_close"):
        return "escalate"
    if lead_info.get("is_objecting"):
        return "objection"
    if lead_info.get("sector") and lead_info.get("pain_point"):
        return "pitch"
    return "qualify"


# ---------------------------------------------------------------------------
# Nó principal — Lusambu responde
# ---------------------------------------------------------------------------

async def lusambu_node(state: LusambuState) -> LusambuState:
    """
    Nó central. Gera resposta, extrai lead info e determina próximo stage.
    Cobre: qualify, pitch, objection, close.
    """
    objection_count = state.get("objection_count", 0)
    turn_count = state.get("turn_count", 0) + 1
    lead_info = state.get("lead_info", {})

    if state.get("stage") == "objection":
        objection_count += 1

    system = SYSTEM_PROMPT.format(
        stage=state.get("stage", "qualify"),
        lead_info=json.dumps(lead_info, ensure_ascii=False, default=str),
        objection_count=objection_count,
    )

    messages_for_llm = [SystemMessage(content=system)] + list(state["messages"])
    response: AIMessage = await llm.ainvoke(messages_for_llm)

    updated_lead_info = await _extract_lead_info(list(state["messages"]) + [response])
    next_stage = _determine_stage(updated_lead_info, objection_count, turn_count)

    escalation_reason = state.get("escalation_reason", "")
    if next_stage == "escalate" and turn_count >= MAX_TURNS:
        escalation_reason = f"Conversa extensa ({turn_count} turnos) — revisão humana"

    await _human_delay()
    await send_whatsapp_message(state["whatsapp_number"], response.content)

    await upsert_lead({
        **updated_lead_info,
        "whatsapp": state["whatsapp_number"],
        "stage": next_stage,
    })

    return {
        **state,
        "messages": [response],
        "lead_info": updated_lead_info,
        "stage": next_stage,
        "objection_count": objection_count,
        "turn_count": turn_count,
        "escalation_reason": escalation_reason,
    }


# ---------------------------------------------------------------------------
# Nó de descarte
# ---------------------------------------------------------------------------

async def discard_node(state: LusambuState) -> LusambuState:
    """Lead não tem empresa. Despedida educada e encerra."""
    message = (
        "Entendo! As nossas soluções são mesmo vocacionadas para empresas. "
        "Se um dia tiveres ou conheceres algum empresário com interesse, "
        "fica à vontade para partilhar. Boa sorte! 👋"
    )
    await _human_delay()
    await send_whatsapp_message(state["whatsapp_number"], message)
    await upsert_lead({
        **state.get("lead_info", {}),
        "whatsapp": state["whatsapp_number"],
        "stage": "descartado",
        "status": "descartado",
    })
    return {**state, "stage": "end"}


# ---------------------------------------------------------------------------
# Nó de escalação para Fidel
# ---------------------------------------------------------------------------

async def escalate_node(state: LusambuState) -> LusambuState:
    """Notifica Fidel via WhatsApp com contexto completo. Avisa o lead."""
    if state.get("fidel_notified"):
        return {**state, "stage": "end"}

    lead = state.get("lead_info", {})
    classification = lead.get("classification", "—").upper()
    emojis = {"HOT": "🔥", "WARM": "🟡", "COLD": "🔵"}
    emoji = emojis.get(classification, "⚪")

    if lead.get("wants_human"):
        reason = "Lead pediu falar com humano"
    elif lead.get("ready_to_close"):
        reason = "Lead pronto para avançar — fecho formal"
    elif state.get("objection_count", 0) >= 2:
        reason = "Objecção repetida — intervenção necessária"
    else:
        reason = state.get("escalation_reason", "Lead qualificado")

    summary = (
        f"🔔 *Lusambu — Intervenção Necessária*\n\n"
        f"👤 Nome: {lead.get('name', '—')}\n"
        f"🏢 Empresa: {lead.get('company', '—')}\n"
        f"📦 Sector: {lead.get('sector', '—')}\n"
        f"💡 Dor: {lead.get('pain_point', '—')}\n"
        f"{emoji} Classificação: {classification}\n\n"
        f"📌 Motivo: {reason}\n"
        f"📱 Número: {state['whatsapp_number']}\n\n"
        f"👉 Entra directamente na conversa quando estiveres pronto."
    )

    await notify_fidel(summary)

    await _human_delay()
    await send_whatsapp_message(
        state["whatsapp_number"],
        "Vou passar-te ao nosso especialista para continuar. Ele entra em contacto ainda hoje. 🙏",
    )

    await upsert_lead({
        **lead,
        "whatsapp": state["whatsapp_number"],
        "stage": "escalado",
        "status": "escalado",
    })

    return {**state, "fidel_notified": True, "stage": "end"}

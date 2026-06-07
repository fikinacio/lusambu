import asyncio
import json
import logging
import os
import random
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage

from .state import LusambuState, LeadInfo
from jinja2 import Template
from .prompts import SYSTEM_PROMPT, EXTRACTION_PROMPT, PITCH_A, PITCH_B, OUTREACH_CONTEXT_TEMPLATE
from integrations.evolution import send_whatsapp_message, send_typing_indicator, notify_fidel
from integrations.supabase_client import upsert_lead, get_outreach_message, get_mensagens_history
from integrations.rag import consultar_conhecimento

logger = logging.getLogger(__name__)

llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=500, temperature=0.7)
llm_extractor = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=300, temperature=0)


def _closing_data_complete(lead_info: LeadInfo) -> bool:
    """Lead forneceu nome e empresa — suficiente para enviar o Calendly."""
    return bool(lead_info.get("name") and lead_info.get("company"))


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


def _determine_stage(
    lead_info: LeadInfo,
    objection_count: int,
    turn_count: int,
    data_confirmed: bool = False,
    calendly_sent: bool = False,
) -> str:
    """Define o próximo stage com base na informação extraída e no progresso do closing."""
    if lead_info.get("has_business") is False:
        return "discard"
    if turn_count >= MAX_TURNS:
        return "escalate"
    if lead_info.get("wants_human") or objection_count >= 2:
        return "escalate"
    if lead_info.get("ready_to_close"):
        # Closing tem 4 sub-etapas geridas pela Lusambu/sistema:
        #   1. recolher name + company
        #   2. recolher scheduled_time
        #   3. apresentar resumo e esperar confirmação
        #   4. sistema envia link Calendly (não LLM)
        # Só escala depois de o link Calendly ser enviado.
        if not _closing_data_complete(lead_info):
            return "closing"
        if not data_confirmed:
            return "closing"
        if not calendly_sent:
            return "closing"
        return "escalate"
    if lead_info.get("is_objecting"):
        return "objection"
    if lead_info.get("sector") and lead_info.get("pain_point"):
        return "pitch"
    return "qualify"


# ---------------------------------------------------------------------------
# Nó de contexto de prospecção — corre uma vez por conversa
# ---------------------------------------------------------------------------

async def load_outreach_context(state: LusambuState) -> LusambuState:
    """Carrega contexto de prospecção e histórico CRM antes de qualquer resposta.

    1. Busca histórico completo da tabela 'mensagens' (entrada + saída).
    2. Busca última mensagem outbound (prospecção) — determina se é outbound/inbound.
    Executa em cada turno para garantir histórico actualizado.
    """
    number = state["whatsapp_number"]
    outreach_msg, historico = await asyncio.gather(
        get_outreach_message(number),
        get_mensagens_history(number),
    )

    # Formata histórico CRM como contexto legível pelo LLM
    mensagens_context = ""
    if historico:
        linhas = []
        for m in historico:
            papel = "BISCA+" if m.get("direcao") == "saida" else "LEAD"
            conteudo = (m.get("conteudo") or "").strip()
            if conteudo:
                linhas.append(f"{papel}: {conteudo}")
        mensagens_context = "\n".join(linhas)

    if outreach_msg:
        return {**state, "outreach_message": outreach_msg, "outreach_source": "outbound", "mensagens_context": mensagens_context}
    return {**state, "outreach_message": None, "outreach_source": "inbound", "mensagens_context": mensagens_context}


# ---------------------------------------------------------------------------
# Nó principal — Lusambu responde
# ---------------------------------------------------------------------------

async def lusambu_node(state: LusambuState) -> LusambuState:
    """
    Nó central. Gera resposta, extrai lead info e determina próximo stage.
    Cobre: qualify, pitch, objection, closing (sub-etapas 1-3).
    A sub-etapa 4 do closing (envio do link Calendly) é tratada aqui sem chamar LLM.
    """
    objection_count = state.get("objection_count", 0)
    turn_count = state.get("turn_count", 0) + 1
    lead_info = state.get("lead_info", {})

    if state.get("stage") == "objection":
        objection_count += 1

    # Atribui variante A/B quando entra em pitch pela primeira vez
    variant = state.get("prompt_variant") or ""
    if not variant and state.get("stage") == "pitch":
        variant = random.choice(["A", "B"])

    # ---- Extracção da nova informação primeiro ----
    offset = state.get("message_offset", 0)
    recent_messages = list(state["messages"])[offset:]

    # Extrai info ANTES de decidir se chamamos o LLM ou enviamos o link Calendly.
    # Precisamos de saber se o lead acabou de confirmar (confirms_data=true).
    extracted_after_user = await _extract_lead_info(recent_messages)

    data_confirmed = state.get("data_confirmed", False) or extracted_after_user.get("confirms_data", False)
    calendly_sent = state.get("calendly_sent", False)

    # ---- Caminho directo: enviar Calendly sem passar pelo LLM ----
    # Condição: estamos em closing, dados completos, lead confirmou agora, link ainda não enviado.
    if (
        state.get("stage") == "closing"
        and _closing_data_complete(extracted_after_user)
        and data_confirmed
        and not calendly_sent
    ):
        link = os.getenv("CALENDLY_LINK", "") or "https://calendly.com/contact-biscaplus/30min"
        link_msg = (
            f"Perfeito. Usa este link para escolheres o horário que te convém — "
            f"leva menos de um minuto: {link}"
        )
        response = AIMessage(content=link_msg)

        await send_typing_indicator(state["whatsapp_number"])
        await _human_delay()
        await send_whatsapp_message(state["whatsapp_number"], link_msg)

        next_stage = _determine_stage(
            extracted_after_user, objection_count, turn_count,
            data_confirmed=True, calendly_sent=True,
        )

        await upsert_lead({
            **extracted_after_user,
            "whatsapp": state["whatsapp_number"],
            "stage": next_stage,
            "prompt_variant": variant or None,
        })

        return {
            **state,
            "messages": [response],
            "lead_info": extracted_after_user,
            "stage": next_stage,
            "objection_count": objection_count,
            "turn_count": turn_count,
            "prompt_variant": variant,
            "data_confirmed": True,
            "calendly_sent": True,
        }

    # ---- RAG: contexto de serviços/casos quando relevante ----
    rag_context = ""
    current_stage = state.get("stage", "qualify")
    if current_stage not in ("closing", "discard", "escalate", "end"):
        last_human = next(
            (m.content for m in reversed(recent_messages) if isinstance(m, HumanMessage)),
            "",
        )
        if last_human:
            rag_context = await consultar_conhecimento(last_human) or ""

    # ---- Caminho normal: gerar resposta com LLM ----
    outreach_ctx = Template(OUTREACH_CONTEXT_TEMPLATE).render(
        outreach_message=state.get("outreach_message")
    )
    system = outreach_ctx + "\n" + SYSTEM_PROMPT.format(
        stage=current_stage,
        lead_info=json.dumps(extracted_after_user, ensure_ascii=False, default=str),
        objection_count=objection_count,
        prompt_variant=variant or "A",
        pitch_instructions=PITCH_B if variant == "B" else PITCH_A,
    )

    mensagens_ctx = state.get("mensagens_context", "")
    if mensagens_ctx:
        system += (
            "\n\n---\nHISTÓRICO CRM (comunicações anteriores com este lead):\n"
            + mensagens_ctx
            + "\n---\n"
            "INSTRUÇÃO CRÍTICA: Esta conversa já está em curso. "
            "NUNCA uses saudações ('Olá', 'Bom dia', 'Boa tarde', etc.) — já foram feitas. "
            "NUNCA te apresentes — já foi feito. "
            "Se o sector, tipo de negócio, empresa ou dor já constarem no histórico, "
            "NÃO perguntes de novo — usa essa informação directamente para avançar a conversa. "
            "Responde de forma natural e directa ao conteúdo da última mensagem do lead."
        )

    if rag_context:
        system += (
            "\n\n---\nCONHECIMENTO BISCA+ (informação verificada sobre serviços e casos reais):\n"
            + rag_context
            + "\n---\n"
            "Usa este contexto se o lead perguntou sobre serviços, sectores ou clientes. "
            "Integra naturalmente — não recites a lista completa."
        )

    messages_for_llm = [SystemMessage(content=system)] + recent_messages
    response = await llm.ainvoke(messages_for_llm)

    # Re-extrai com a resposta da Lusambu incluída (útil para detectar quando o resumo de
    # confirmação acabou de ser apresentado — relevante na próxima iteração)
    updated_lead_info = await _extract_lead_info(recent_messages + [response])

    next_stage = _determine_stage(
        updated_lead_info, objection_count, turn_count,
        data_confirmed=data_confirmed, calendly_sent=calendly_sent,
    )

    escalation_reason = state.get("escalation_reason", "")
    if next_stage == "escalate" and turn_count >= MAX_TURNS:
        escalation_reason = f"Conversa extensa ({turn_count} turnos) — revisão humana"

    if next_stage != "escalate":
        await send_typing_indicator(state["whatsapp_number"])
        await _human_delay()
        await send_whatsapp_message(state["whatsapp_number"], response.content)

    await upsert_lead({
        **updated_lead_info,
        "whatsapp": state["whatsapp_number"],
        "stage": next_stage,
        "prompt_variant": variant or None,
    })

    return {
        **state,
        "messages": [response],
        "lead_info": updated_lead_info,
        "stage": next_stage,
        "objection_count": objection_count,
        "turn_count": turn_count,
        "prompt_variant": variant,
        "escalation_reason": escalation_reason,
        "data_confirmed": data_confirmed,
        "calendly_sent": calendly_sent,
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
    await send_typing_indicator(state["whatsapp_number"])
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
    """Notifica Fidel via WhatsApp com contexto completo.

    Envia mensagem ao lead apenas no fluxo Lusambu (sem Calendly enviado e sem Sales Agent activo).
    No fluxo Sales Agent (escala_para_fidel ou conversa_encerrada), o fecho é silencioso —
    o Sales Agent já comunicou com o lead nesse turno.
    """
    if state.get("fidel_notified"):
        return {**state, "stage": "end"}

    lead = state.get("lead_info", {})

    # Detalhes da proposta preenchidos pelo supervisor
    # — usados como fallback quando lead_info não tem dados (fluxo Sales Agent)
    sup_decision = state.get("supervisor_decision") or {}
    sup_resumo = sup_decision.get("resumo_para_fidel", "")

    nome = lead.get("name") or sup_decision.get("nome_lead") or "a confirmar"
    empresa = lead.get("company") or sup_decision.get("empresa_lead") or "a confirmar"

    # Classificação: supervisor tem prioridade (vê a conversa completa incluindo Sales Agent)
    sup_class = (sup_decision.get("classificacao") or "").upper()
    lead_class = (lead.get("classification") or "—").upper()
    classification = sup_class if sup_class in ("HOT", "WARM", "COLD") else lead_class

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
        f"👤 Nome: {nome}\n"
        f"🏢 Empresa: {empresa}\n"
        f"📦 Sector: {lead.get('sector') or '—'}\n"
        f"💡 Dor: {lead.get('pain_point') or sup_decision.get('dor_confirmada') or '—'}\n"
        f"🗓️ Agendamento: {lead.get('scheduled_time') or 'Pendente'}\n"
        f"🔥 Classificação: {classification}\n\n"
        f"📌 Motivo: {reason}\n"
        f"📱 Número: {state['whatsapp_number']}\n\n"
        f"👉 Entra directamente na conversa quando estiveres pronto."
    )

    if sup_resumo:
        summary += f"\n\n📋 Proposta: {sup_resumo}"

    await notify_fidel(summary)

    # Enviar mensagem ao lead APENAS no fluxo Lusambu sem Calendly:
    # - calendly_sent=True → lead já tem o link, não interromper
    # - sales_agent_active=True → Sales Agent já comunicou neste turno; fecho é silencioso
    if not state.get("calendly_sent") and not state.get("sales_agent_active"):
        await send_typing_indicator(state["whatsapp_number"])
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

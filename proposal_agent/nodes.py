import logging
import os

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.types import interrupt

from .state import ProposalState
from .prompts import PROPOSAL_SYSTEM_PROMPT, PROPOSAL_EDIT_SYSTEM_PROMPT, APPROVAL_BUTTONS
from integrations.evolution import send_whatsapp_message, send_button_message, send_media_message
from integrations.supabase_client import (
    get_lead_for_proposal,
    get_company_config,
    save_proposal_draft,
    update_proposal_draft,
    upsert_lead,
)

logger = logging.getLogger(__name__)

llm_proposal = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=800, temperature=0.3)

FIDEL_NUMBER = os.getenv("FIDEL_WHATSAPP", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_decision(text: str) -> str:
    """Normaliza resposta do Fidel para 'aprovar' | 'editar' | 'rejeitar' | ''."""
    t = text.strip().lower()
    if t in ("1", "aprovar", "✅ aprovar", "✅aprovar", "approve"):
        return "aprovar"
    if t in ("2", "editar", "✏️ editar", "✏️editar", "edit", "corrigir"):
        return "editar"
    if t in ("3", "rejeitar", "❌ rejeitar", "❌rejeitar", "reject"):
        return "rejeitar"
    # Partial match
    if "aprov" in t:
        return "aprovar"
    if "edit" in t or "corri" in t or "muda" in t:
        return "editar"
    if "rejeit" in t or "nao" in t:
        return "rejeitar"
    return ""


# ---------------------------------------------------------------------------
# Nós
# ---------------------------------------------------------------------------

async def load_context_node(state: ProposalState) -> ProposalState:
    """Lê dados do lead e configuração da empresa no Supabase."""
    lead = await get_lead_for_proposal(state["whatsapp"])
    cfg = await get_company_config()
    if not lead:
        logger.warning(f"Lead não encontrado para proposta: {state['whatsapp']}")
        return {**state, "company_config": cfg}
    return {
        **state,
        "empresa": lead.get("company") or "",
        "sector": lead.get("sector") or "",
        "dores": lead.get("pain_point") or "",
        "notas_sales": lead.get("notas_sales") or "",
        "valor_negociado": lead.get("valor_negociado") or "",
        "company_config": cfg,
    }


async def generate_proposal_node(state: ProposalState) -> ProposalState:
    """Gera texto da proposta via LLM."""
    cfg = state.get("company_config", {})
    prompt = PROPOSAL_SYSTEM_PROMPT.format(
        company_name=cfg.get("company_name", "Bisca+"),
        nif=cfg.get("nif", ""),
        address=cfg.get("address", ""),
        brand_name=cfg.get("brand_name", "Bisca+"),
        fidel_name=cfg.get("fidel_name", "Fidel Kussunga"),
        empresa=state.get("empresa", ""),
        sector=state.get("sector", ""),
        dores=state.get("dores", ""),
        notas_sales=state.get("notas_sales", ""),
        valor_negociado=state.get("valor_negociado", ""),
    )
    response = await llm_proposal.ainvoke([SystemMessage(content=prompt)])
    return {**state, "proposal_text": response.content.strip()}


async def regenerate_proposal_node(state: ProposalState) -> ProposalState:
    """Regenera a proposta incorporando as correcções do Fidel."""
    prompt = PROPOSAL_EDIT_SYSTEM_PROMPT.format(
        proposal_text=state.get("proposal_text", ""),
        edit_notes=state.get("edit_notes", ""),
    )
    response = await llm_proposal.ainvoke([SystemMessage(content=prompt)])
    iteration = state.get("iteration", 0) + 1
    return {**state, "proposal_text": response.content.strip(), "iteration": iteration}


async def send_to_fidel_node(state: ProposalState) -> ProposalState:
    """Guarda rascunho no Supabase e envia proposta + botões ao Fidel."""
    draft_id = state.get("draft_id")
    proposal_text = state.get("proposal_text", "")

    # Guardar/actualizar rascunho
    if not draft_id:
        draft_id = await save_proposal_draft({
            "whatsapp": state["whatsapp"],
            "empresa": state.get("empresa", ""),
            "sector": state.get("sector", ""),
            "dores": state.get("dores", ""),
            "notas_sales": state.get("notas_sales", ""),
            "valor_negociado": state.get("valor_negociado", ""),
            "proposal_text": proposal_text,
            "status": "pending",
            "iteration": state.get("iteration", 0),
        })
    else:
        await update_proposal_draft(draft_id, {
            "proposal_text": proposal_text,
            "status": "pending",
            "edit_notes": None,
            "iteration": state.get("iteration", 0),
        })

    # Enviar logótipo se configurado
    logo_url = (state.get("company_config") or {}).get("logo_url", "")
    if logo_url:
        await send_media_message(FIDEL_NUMBER, logo_url, mediatype="image", caption="")

    # Enviar texto da proposta
    empresa = state.get("empresa", "lead")
    header = f"📋 *Proposta para {empresa}*\n\n"
    await send_whatsapp_message(FIDEL_NUMBER, header + proposal_text)

    # Enviar botões de decisão
    iteration = state.get("iteration", 0)
    footer = f"Iteração {iteration + 1}" if iteration > 0 else "Fidel Kussunga | Bisca+"
    await send_button_message(
        number=FIDEL_NUMBER,
        body_text="Revisaste a proposta. Qual é a tua decisão?",
        buttons=APPROVAL_BUTTONS,
        footer=footer,
    )

    return {**state, "draft_id": draft_id or ""}


async def wait_for_fidel_node(state: ProposalState) -> ProposalState:
    """Pausa o grafo e aguarda resposta do Fidel via interrupt."""
    fidel_message: str = interrupt("Aguarda decisão do Fidel (aprovar / editar / rejeitar)")
    decision = _parse_decision(fidel_message)
    return {
        **state,
        "fidel_decision": decision,
        "edit_notes": fidel_message if decision == "editar" else "",
    }


async def send_to_client_node(state: ProposalState) -> ProposalState:
    """Envia proposta aprovada ao lead via WhatsApp."""
    cfg = state.get("company_config", {})
    logo_url = cfg.get("logo_url", "")
    if logo_url:
        await send_media_message(state["whatsapp"], logo_url, mediatype="image", caption="")
    await send_whatsapp_message(state["whatsapp"], state.get("proposal_text", ""))
    logger.info(f"Proposta enviada ao cliente {state['whatsapp']}")
    return state


async def mark_approved_node(state: ProposalState) -> ProposalState:
    """Actualiza status para sent no Supabase."""
    draft_id = state.get("draft_id", "")
    if draft_id:
        await update_proposal_draft(draft_id, {"status": "sent"})
    await upsert_lead({"whatsapp": state["whatsapp"], "status": "proposta_enviada"})
    return state


async def mark_rejected_node(state: ProposalState) -> ProposalState:
    """Actualiza status para rejected."""
    draft_id = state.get("draft_id", "")
    if draft_id:
        await update_proposal_draft(draft_id, {"status": "rejected"})
    await upsert_lead({"whatsapp": state["whatsapp"], "status": "proposta_rejeitada"})
    logger.info(f"Proposta rejeitada para {state['whatsapp']}")
    return state

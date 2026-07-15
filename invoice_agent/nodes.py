import logging
import os
from datetime import datetime, timezone

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.types import interrupt

from .state import InvoiceState
from .prompts import INVOICE_SYSTEM_PROMPT, INVOICE_EDIT_SYSTEM_PROMPT, APPROVAL_BUTTONS
from integrations.evolution import send_whatsapp_message, send_button_message
from integrations.supabase_client import (
    get_lead_for_invoice,
    get_company_config,
    save_invoice_draft,
    update_invoice_draft,
    upsert_lead,
)
from integrations.invoiceninja import get_or_create_client, create_invoice, send_invoice_email

logger = logging.getLogger(__name__)

llm_invoice = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=600, temperature=0.3)

FIDEL_NUMBER = os.getenv("FIDEL_WHATSAPP_NUMBER", "")


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

async def load_context_node(state: InvoiceState) -> InvoiceState:
    """Lê dados do lead e configuração da empresa no Supabase."""
    lead = await get_lead_for_invoice(state["whatsapp"])
    cfg = await get_company_config()
    if not lead:
        logger.warning(f"Lead não encontrado para factura: {state['whatsapp']}")
        return {**state, "company_config": cfg}
    return {
        **state,
        "empresa": lead.get("company") or "",
        "sector": lead.get("sector") or "",
        "email": lead.get("email") or "",
        "valor_negociado": lead.get("valor_negociado") or "",
        "company_config": cfg,
    }


async def generate_preview_node(state: InvoiceState) -> InvoiceState:
    """Gera pré-visualização da factura via LLM."""
    cfg = state.get("company_config", {})
    prompt = INVOICE_SYSTEM_PROMPT.format(
        company_name=cfg.get("company_name", "BMST"),
        nif=cfg.get("nif", ""),
        address=cfg.get("address", ""),
        empresa=state.get("empresa", ""),
        sector=state.get("sector", ""),
        valor_negociado=state.get("valor_negociado", ""),
    )
    response = await llm_invoice.ainvoke([SystemMessage(content=prompt)])
    return {**state, "invoice_preview": response.content.strip()}


async def regenerate_preview_node(state: InvoiceState) -> InvoiceState:
    """Regenera a pré-visualização incorporando as correcções do Fidel."""
    prompt = INVOICE_EDIT_SYSTEM_PROMPT.format(
        invoice_preview=state.get("invoice_preview", ""),
        edit_notes=state.get("edit_notes", ""),
    )
    response = await llm_invoice.ainvoke([SystemMessage(content=prompt)])
    iteration = state.get("iteration", 0) + 1
    return {**state, "invoice_preview": response.content.strip(), "iteration": iteration}


async def send_to_fidel_node(state: InvoiceState) -> InvoiceState:
    """Guarda rascunho no Supabase e envia pré-visualização + botões ao Fidel."""
    draft_id = state.get("invoice_draft_id")
    invoice_preview = state.get("invoice_preview", "")

    if not draft_id:
        draft_id = await save_invoice_draft({
            "whatsapp": state["whatsapp"],
            "empresa": state.get("empresa", ""),
            "sector": state.get("sector", ""),
            "email": state.get("email", ""),
            "valor_negociado": state.get("valor_negociado", ""),
            "invoice_preview": invoice_preview,
            "status": "pending",
            "iteration": state.get("iteration", 0),
        })
    else:
        await update_invoice_draft(draft_id, {
            "invoice_preview": invoice_preview,
            "status": "pending",
            "edit_notes": None,
            "iteration": state.get("iteration", 0),
        })

    empresa = state.get("empresa", "lead")
    header = f"📄 *Pré-visualização de Factura para {empresa}*\n\n"
    await send_whatsapp_message(FIDEL_NUMBER, header + invoice_preview)

    iteration = state.get("iteration", 0)
    footer = f"Iteração {iteration + 1}" if iteration > 0 else "Fidel Kussunga | BMST"
    await send_button_message(
        number=FIDEL_NUMBER,
        body_text="Reviste a factura. Qual é a tua decisão?",
        buttons=APPROVAL_BUTTONS,
        footer=footer,
    )

    return {**state, "invoice_draft_id": draft_id or ""}


async def wait_for_fidel_node(state: InvoiceState) -> InvoiceState:
    """Pausa o grafo e aguarda resposta do Fidel via interrupt."""
    fidel_message: str = interrupt("Aguarda decisão do Fidel (aprovar / editar / rejeitar)")
    decision = _parse_decision(fidel_message)
    return {
        **state,
        "fidel_decision": decision,
        "edit_notes": fidel_message if decision == "editar" else "",
    }


async def finalize_invoice_node(state: InvoiceState) -> InvoiceState:
    """Cria cliente e factura no InvoiceNinja, envia ao cliente, regista no Supabase."""
    empresa = state.get("empresa", "")
    email = state.get("email", "")
    valor_negociado = state.get("valor_negociado", "")
    draft_id = state.get("invoice_draft_id", "")

    # 1. Encontrar ou criar cliente no InvoiceNinja
    client_id = await get_or_create_client(empresa, email)

    # 2. Criar factura
    inv_data = await create_invoice(client_id, valor_negociado, empresa)
    invoice_id = inv_data["invoice_id"]
    invoice_number = inv_data["invoice_number"]

    # 3. Enviar factura por email ao cliente
    await send_invoice_email(invoice_id)

    # 4. Registar no Supabase
    now = datetime.now(timezone.utc).isoformat()
    if draft_id:
        await update_invoice_draft(draft_id, {
            "status": "sent",
            "client_id": client_id,
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "data_faturacao": now,
            "status_pagamento": "pendente",
        })

    await upsert_lead({"whatsapp": state["whatsapp"], "status": "fatura_enviada"})
    logger.info(f"Factura {invoice_number} enviada ao cliente {email}")

    return {
        **state,
        "client_id": client_id,
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
    }


async def notify_rejection_node(state: InvoiceState) -> InvoiceState:
    """Regista rejeição e actualiza status do lead."""
    draft_id = state.get("invoice_draft_id", "")
    if draft_id:
        await update_invoice_draft(draft_id, {"status": "rejected"})
    await upsert_lead({"whatsapp": state["whatsapp"], "status": "fatura_rejeitada"})
    logger.info(f"Factura rejeitada para {state['whatsapp']}")
    return state

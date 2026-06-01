import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from langchain_anthropic import ChatAnthropic
from invoice_agent.state import InvoiceState
import invoice_agent.nodes as inv


def _base_state() -> InvoiceState:
    return {
        "whatsapp": "244923000000",
        "empresa": "Acme",
        "sector": "retail",
        "email": "acme@example.com",
        "valor_negociado": "250.000 Kz/mês",
        "company_config": {
            "company_name": "BISCA MAIS",
            "nif": "003378815UE037",
            "address": "Rua Francisco António",
            "brand_name": "Bisca+",
        },
        "invoice_preview": "",
        "fidel_decision": "",
        "edit_notes": "",
        "iteration": 0,
    }


# ---------------------------------------------------------------------------
# load_context_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_context_node_populates_fields():
    lead = {
        "company": "Acme", "sector": "retail",
        "email": "acme@example.com", "valor_negociado": "250k",
    }
    cfg = {"company_name": "BISCA MAIS", "nif": "003", "address": "Rua X"}
    with patch("invoice_agent.nodes.get_lead_for_invoice", AsyncMock(return_value=lead)), \
         patch("invoice_agent.nodes.get_company_config", AsyncMock(return_value=cfg)):
        result = await inv.load_context_node({"whatsapp": "244923000000"})
    assert result["empresa"] == "Acme"
    assert result["email"] == "acme@example.com"
    assert result["company_config"]["nif"] == "003"


@pytest.mark.asyncio
async def test_load_context_node_lead_not_found():
    with patch("invoice_agent.nodes.get_lead_for_invoice", AsyncMock(return_value=None)), \
         patch("invoice_agent.nodes.get_company_config", AsyncMock(return_value={})):
        result = await inv.load_context_node({"whatsapp": "244923000000"})
    assert result.get("empresa", "") == ""


# ---------------------------------------------------------------------------
# generate_preview_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_preview_node_calls_llm():
    state = _base_state()
    mock_response = MagicMock()
    mock_response.content = "*📄 PRÉ-VISUALIZAÇÃO DE FACTURA*\n\n*Cliente:* Acme"
    with patch.object(ChatAnthropic, "ainvoke", AsyncMock(return_value=mock_response)):
        result = await inv.generate_preview_node(state)
    assert "*📄 PRÉ-VISUALIZAÇÃO DE FACTURA*" in result["invoice_preview"]


# ---------------------------------------------------------------------------
# regenerate_preview_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regenerate_preview_node_increments_iteration():
    state = _base_state()
    state["invoice_preview"] = "Preview original."
    state["edit_notes"] = "Mudar condições para 60 dias"
    mock_response = MagicMock()
    mock_response.content = "Preview actualizado com 60 dias."
    with patch.object(ChatAnthropic, "ainvoke", AsyncMock(return_value=mock_response)):
        result = await inv.regenerate_preview_node(state)
    assert result["invoice_preview"] == "Preview actualizado com 60 dias."
    assert result["iteration"] == 1


# ---------------------------------------------------------------------------
# send_to_fidel_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_to_fidel_node_new_draft():
    state = _base_state()
    state["invoice_preview"] = "Texto da factura."
    with patch("invoice_agent.nodes.save_invoice_draft", AsyncMock(return_value="uuid-1234")), \
         patch("invoice_agent.nodes.update_invoice_draft", AsyncMock()), \
         patch("invoice_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("invoice_agent.nodes.send_button_message", AsyncMock(return_value=True)):
        result = await inv.send_to_fidel_node(state)
    assert result["invoice_draft_id"] == "uuid-1234"


@pytest.mark.asyncio
async def test_send_to_fidel_node_existing_draft_calls_update():
    state = _base_state()
    state["invoice_draft_id"] = "existing-uuid"
    state["invoice_preview"] = "Preview actualizado."
    with patch("invoice_agent.nodes.save_invoice_draft", AsyncMock()) as mock_save, \
         patch("invoice_agent.nodes.update_invoice_draft", AsyncMock()) as mock_update, \
         patch("invoice_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("invoice_agent.nodes.send_button_message", AsyncMock(return_value=True)):
        result = await inv.send_to_fidel_node(state)
    mock_save.assert_not_called()
    mock_update.assert_called_once()
    assert result["invoice_draft_id"] == "existing-uuid"


# ---------------------------------------------------------------------------
# _parse_decision
# ---------------------------------------------------------------------------

def test_parse_decision_aprovar():
    assert inv._parse_decision("aprovar") == "aprovar"
    assert inv._parse_decision("1") == "aprovar"
    assert inv._parse_decision("✅ Aprovar") == "aprovar"
    assert inv._parse_decision("APROVAR") == "aprovar"


def test_parse_decision_editar():
    assert inv._parse_decision("editar") == "editar"
    assert inv._parse_decision("2") == "editar"
    assert inv._parse_decision("✏️ Editar") == "editar"


def test_parse_decision_rejeitar():
    assert inv._parse_decision("rejeitar") == "rejeitar"
    assert inv._parse_decision("3") == "rejeitar"
    assert inv._parse_decision("❌ Rejeitar") == "rejeitar"


def test_parse_decision_unknown():
    assert inv._parse_decision("não percebo") == ""


# ---------------------------------------------------------------------------
# finalize_invoice_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_invoice_node_calls_all_steps():
    state = _base_state()
    state["invoice_draft_id"] = "uuid-1234"

    with patch("invoice_agent.nodes.get_or_create_client", AsyncMock(return_value="client-abc")) as mock_client, \
         patch("invoice_agent.nodes.create_invoice", AsyncMock(return_value={"invoice_id": "inv-001", "invoice_number": "0001"})) as mock_inv, \
         patch("invoice_agent.nodes.send_invoice_email", AsyncMock(return_value=True)) as mock_email, \
         patch("invoice_agent.nodes.update_invoice_draft", AsyncMock()) as mock_update, \
         patch("invoice_agent.nodes.upsert_lead", AsyncMock(return_value=True)) as mock_upsert:
        result = await inv.finalize_invoice_node(state)

    mock_client.assert_called_once_with("Acme", "acme@example.com")
    mock_inv.assert_called_once_with("client-abc", "250.000 Kz/mês", "Acme")
    mock_email.assert_called_once_with("inv-001")
    mock_update.assert_called_once()
    update_args = mock_update.call_args[0]
    assert update_args[0] == "uuid-1234"
    assert update_args[1]["status"] == "sent"
    assert update_args[1]["status_pagamento"] == "pendente"
    mock_upsert.assert_called_once_with({"whatsapp": "244923000000", "status": "fatura_enviada"})

    assert result["client_id"] == "client-abc"
    assert result["invoice_id"] == "inv-001"
    assert result["invoice_number"] == "0001"


# ---------------------------------------------------------------------------
# notify_rejection_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_rejection_node_updates_db():
    state = _base_state()
    state["invoice_draft_id"] = "uuid-1234"
    with patch("invoice_agent.nodes.update_invoice_draft", AsyncMock()) as mock_update, \
         patch("invoice_agent.nodes.upsert_lead", AsyncMock(return_value=True)) as mock_upsert:
        await inv.notify_rejection_node(state)
    mock_update.assert_called_once_with("uuid-1234", {"status": "rejected"})
    mock_upsert.assert_called_once_with({"whatsapp": "244923000000", "status": "fatura_rejeitada"})

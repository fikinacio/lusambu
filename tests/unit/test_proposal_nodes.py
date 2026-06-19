import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_anthropic import ChatAnthropic
from proposal_agent.state import ProposalState
import proposal_agent.nodes as pn


def _base_state() -> ProposalState:
    return {
        "whatsapp": "244923000000",
        "empresa": "Acme",
        "sector": "retail",
        "dores": "sem CRM",
        "notas_sales": "quer integração WhatsApp",
        "valor_negociado": "250.000 Kz/mês",
        "company_config": {
            "company_name": "BISCA MAIS",
            "nif": "003378815UE037",
            "address": "Rua Francisco António",
            "brand_name": "BMST",
            "fidel_name": "Fidel Kussunga",
            "logo_url": "",
        },
        "proposal_text": "",
        "fidel_decision": "",
        "edit_notes": "",
        "iteration": 0,
    }


@pytest.mark.asyncio
async def test_load_context_node_populates_fields():
    lead = {
        "company": "Acme", "sector": "retail",
        "pain_point": "sem CRM", "notas_sales": "quer WA",
        "valor_negociado": "250k",
    }
    cfg = {"company_name": "BISCA MAIS", "nif": "003", "address": "Rua X",
           "brand_name": "BMST", "fidel_name": "Fidel", "logo_url": ""}
    with patch("proposal_agent.nodes.get_lead_for_proposal", AsyncMock(return_value=lead)), \
         patch("proposal_agent.nodes.get_company_config", AsyncMock(return_value=cfg)):
        result = await pn.load_context_node({"whatsapp": "244923000000"})
    assert result["empresa"] == "Acme"
    assert result["company_config"]["nif"] == "003"


@pytest.mark.asyncio
async def test_load_context_node_lead_not_found():
    with patch("proposal_agent.nodes.get_lead_for_proposal", AsyncMock(return_value=None)), \
         patch("proposal_agent.nodes.get_company_config", AsyncMock(return_value={})):
        result = await pn.load_context_node({"whatsapp": "244923000000"})
    assert result.get("empresa", "") == ""


@pytest.mark.asyncio
async def test_generate_proposal_node_calls_llm():
    state = _base_state()
    mock_response = MagicMock()
    mock_response.content = "*1. Diagnóstico*\nTexto.\n*2. Solução*\nSolução."
    with patch.object(ChatAnthropic, "ainvoke", AsyncMock(return_value=mock_response)):
        result = await pn.generate_proposal_node(state)
    assert "*1. Diagnóstico*" in result["proposal_text"]


@pytest.mark.asyncio
async def test_regenerate_proposal_node_increments_iteration():
    state = _base_state()
    state["proposal_text"] = "Proposta original."
    state["edit_notes"] = "Mudar valor para 300k"
    mock_response = MagicMock()
    mock_response.content = "Proposta actualizada com 300k."
    with patch.object(ChatAnthropic, "ainvoke", AsyncMock(return_value=mock_response)):
        result = await pn.regenerate_proposal_node(state)
    assert result["proposal_text"] == "Proposta actualizada com 300k."
    assert result["iteration"] == 1


@pytest.mark.asyncio
async def test_send_to_fidel_node_new_draft():
    state = _base_state()
    state["proposal_text"] = "Texto da proposta."
    with patch("proposal_agent.nodes.save_proposal_draft", AsyncMock(return_value="uuid-1234")), \
         patch("proposal_agent.nodes.update_proposal_draft", AsyncMock()), \
         patch("proposal_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("proposal_agent.nodes.send_button_message", AsyncMock(return_value=True)), \
         patch("proposal_agent.nodes.send_media_message", AsyncMock(return_value=True)):
        result = await pn.send_to_fidel_node(state)
    assert result["draft_id"] == "uuid-1234"


@pytest.mark.asyncio
async def test_send_to_fidel_node_existing_draft_calls_update():
    state = _base_state()
    state["draft_id"] = "existing-uuid"
    state["proposal_text"] = "Proposta actualizada."
    with patch("proposal_agent.nodes.save_proposal_draft", AsyncMock()) as mock_save, \
         patch("proposal_agent.nodes.update_proposal_draft", AsyncMock()) as mock_update, \
         patch("proposal_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("proposal_agent.nodes.send_button_message", AsyncMock(return_value=True)), \
         patch("proposal_agent.nodes.send_media_message", AsyncMock(return_value=True)):
        result = await pn.send_to_fidel_node(state)
    mock_save.assert_not_called()
    mock_update.assert_called_once()
    assert result["draft_id"] == "existing-uuid"


def test_parse_fidel_decision_aprovar():
    assert pn._parse_decision("aprovar") == "aprovar"
    assert pn._parse_decision("1") == "aprovar"
    assert pn._parse_decision("✅ Aprovar") == "aprovar"
    assert pn._parse_decision("APROVAR") == "aprovar"


def test_parse_fidel_decision_editar():
    assert pn._parse_decision("editar") == "editar"
    assert pn._parse_decision("2") == "editar"
    assert pn._parse_decision("✏️ Editar") == "editar"


def test_parse_fidel_decision_rejeitar():
    assert pn._parse_decision("rejeitar") == "rejeitar"
    assert pn._parse_decision("3") == "rejeitar"
    assert pn._parse_decision("❌ Rejeitar") == "rejeitar"


def test_parse_fidel_decision_unknown():
    assert pn._parse_decision("não percebo") == ""


@pytest.mark.asyncio
async def test_mark_approved_node_updates_db():
    state = _base_state()
    state["draft_id"] = "uuid-1234"
    with patch("proposal_agent.nodes.update_proposal_draft", AsyncMock()) as mock_update, \
         patch("proposal_agent.nodes.upsert_lead", AsyncMock(return_value=True)) as mock_upsert:
        await pn.mark_approved_node(state)
    mock_update.assert_called_once_with("uuid-1234", {"status": "sent"})
    mock_upsert.assert_called_once_with({"whatsapp": "244923000000", "status": "proposta_enviada"})


@pytest.mark.asyncio
async def test_mark_rejected_node_updates_db():
    state = _base_state()
    state["draft_id"] = "uuid-1234"
    with patch("proposal_agent.nodes.update_proposal_draft", AsyncMock()) as mock_update, \
         patch("proposal_agent.nodes.upsert_lead", AsyncMock(return_value=True)) as mock_upsert:
        await pn.mark_rejected_node(state)
    mock_update.assert_called_once_with("uuid-1234", {"status": "rejected"})
    mock_upsert.assert_called_once_with({"whatsapp": "244923000000", "status": "proposta_rejeitada"})

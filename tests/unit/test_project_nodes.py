import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_anthropic import ChatAnthropic
from project_agent.state import ProjectState
import project_agent.nodes as pn


def _base_state() -> dict:
    return {
        "whatsapp": "244923000000",
        "empresa": "Acme",
        "servico_tipo": "Chatbots & Assistentes IA",
        "valor": 250000.0,
        "contact_name": "Joao",
        "email": "acme@example.com",
        "canal_preferido": "whatsapp",
        "company_config": {"company_name": "Bisca+"},
        "milestones": [],
        "milestones_preview": "",
        "fidel_decision": "",
        "edit_notes": "",
        "iteration": 0,
    }


# ---------------------------------------------------------------------------
# _milestone_template
# ---------------------------------------------------------------------------

def test_milestone_template_chatbot():
    result = pn._milestone_template("Chatbots & Assistentes IA")
    assert len(result) == 5
    assert result[0]["ordem"] == 1


def test_milestone_template_automacao():
    result = pn._milestone_template("Automacao de Processos")
    assert len(result) == 5
    assert "Kickoff" in result[0]["nome"]


def test_milestone_template_fallback():
    result = pn._milestone_template("outro servico desconhecido")
    assert len(result) == 5


def test_milestone_template_retainer():
    result = pn._milestone_template("Retainer")
    assert len(result) == 4


# ---------------------------------------------------------------------------
# _parse_decision
# ---------------------------------------------------------------------------

def test_parse_decision_aprovar():
    assert pn._parse_decision("aprovar") == "aprovar"
    assert pn._parse_decision("1") == "aprovar"
    assert pn._parse_decision("aprovado") == "aprovar"


def test_parse_decision_editar():
    assert pn._parse_decision("editar") == "editar"
    assert pn._parse_decision("2") == "editar"
    assert pn._parse_decision("muda a data") == "editar"


def test_parse_decision_unknown_defaults_to_editar():
    assert pn._parse_decision("texto aleatorio") == "editar"


# ---------------------------------------------------------------------------
# load_context_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_context_node_populates_fields():
    deal = {
        "empresa": "Acme", "sector": "Chatbots", "email": "a@b.com",
        "valor": 1000.0, "contact_name": "Joao",
    }
    cfg = {"company_name": "Bisca+"}
    with patch("project_agent.nodes.get_deal_for_project", AsyncMock(return_value=deal)), \
         patch("project_agent.nodes.get_company_config", AsyncMock(return_value=cfg)):
        result = await pn.load_context_node({"whatsapp": "244923000000"})
    assert result["empresa"] == "Acme"
    assert result["email"] == "a@b.com"
    assert result["company_config"]["company_name"] == "Bisca+"


@pytest.mark.asyncio
async def test_load_context_node_deal_not_found():
    with patch("project_agent.nodes.get_deal_for_project", AsyncMock(return_value=None)), \
         patch("project_agent.nodes.get_company_config", AsyncMock(return_value={})):
        with pytest.raises(ValueError, match="Deal não encontrado"):
            await pn.load_context_node({"whatsapp": "244923000000"})


# ---------------------------------------------------------------------------
# generate_milestones_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_milestones_node_populates_state():
    state = _base_state()
    mock_response = MagicMock()
    mock_response.content = "*Plano de Projecto Acme*\n1. Kickoff"
    with patch.object(ChatAnthropic, "ainvoke", AsyncMock(return_value=mock_response)):
        result = await pn.generate_milestones_node(state)
    assert len(result["milestones"]) > 0
    assert "data_prevista" in result["milestones"][0]
    assert "Plano de Projecto" in result["milestones_preview"]


# ---------------------------------------------------------------------------
# regenerate_milestones_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regenerate_milestones_node_increments_iteration():
    state = _base_state()
    state["milestones_preview"] = "Preview original."
    state["edit_notes"] = "Mudar data do milestone 3."
    mock_response = MagicMock()
    mock_response.content = "Preview actualizado."
    with patch.object(ChatAnthropic, "ainvoke", AsyncMock(return_value=mock_response)):
        result = await pn.regenerate_milestones_node(state)
    assert result["milestones_preview"] == "Preview actualizado."
    assert result["iteration"] == 1


# ---------------------------------------------------------------------------
# send_to_fidel_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_to_fidel_node_new_project():
    state = _base_state()
    state["milestones_preview"] = "Texto do plano."
    with patch("project_agent.nodes.save_project", AsyncMock(return_value="proj-uuid")) as mock_save, \
         patch("project_agent.nodes.update_project", AsyncMock()) as mock_update, \
         patch("project_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("project_agent.nodes.send_button_message", AsyncMock(return_value=True)):
        result = await pn.send_to_fidel_node(state)
    mock_save.assert_called_once()
    mock_update.assert_not_called()
    assert result["project_id"] == "proj-uuid"


@pytest.mark.asyncio
async def test_send_to_fidel_node_existing_calls_update():
    state = _base_state()
    state["project_id"] = "existing-proj"
    state["milestones_preview"] = "Preview actualizado."
    with patch("project_agent.nodes.save_project", AsyncMock()) as mock_save, \
         patch("project_agent.nodes.update_project", AsyncMock()) as mock_update, \
         patch("project_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("project_agent.nodes.send_button_message", AsyncMock(return_value=True)):
        result = await pn.send_to_fidel_node(state)
    mock_save.assert_not_called()
    mock_update.assert_called_once()
    assert result["project_id"] == "existing-proj"


# ---------------------------------------------------------------------------
# create_notion_page_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_notion_page_node_sets_page_id():
    state = _base_state()
    state["milestones"] = [{"nome": "Kickoff", "ordem": 1, "data_prevista": "2026-06-05"}]
    with patch("project_agent.nodes.create_project_page", AsyncMock(return_value="page-xyz")):
        result = await pn.create_notion_page_node(state)
    assert result["notion_page_id"] == "page-xyz"


# ---------------------------------------------------------------------------
# save_project_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_project_node_calls_update_and_milestones():
    state = _base_state()
    state["project_id"] = "proj-uuid"
    state["notion_page_id"] = "page-xyz"
    state["milestones"] = [{"nome": "Kickoff", "ordem": 1, "data_prevista": "2026-06-05"}]
    with patch("project_agent.nodes.update_project", AsyncMock()) as mock_update, \
         patch("project_agent.nodes.save_project_milestones", AsyncMock()) as mock_milestones:
        await pn.save_project_node(state)
    mock_update.assert_called_once()
    update_args = mock_update.call_args[0]
    assert update_args[0] == "proj-uuid"
    assert update_args[1]["status"] == "em_curso"
    mock_milestones.assert_called_once()
    ms_args = mock_milestones.call_args[0]
    assert ms_args[0] == "proj-uuid"
    assert ms_args[1][0]["nome"] == "Kickoff"


# ---------------------------------------------------------------------------
# send_welcome_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_welcome_node_sends_message_and_logs():
    state = _base_state()
    state["notion_page_id"] = "page-xyz"
    with patch("project_agent.nodes.send_whatsapp_message", AsyncMock(return_value=True)) as mock_wa, \
         patch("project_agent.nodes.add_communication_log", AsyncMock(return_value=True)) as mock_log:
        await pn.send_welcome_node(state)
    mock_wa.assert_called_once()
    call_num, call_msg = mock_wa.call_args[0]
    assert call_num == "244923000000"
    assert "Joao" in call_msg
    mock_log.assert_called_once()

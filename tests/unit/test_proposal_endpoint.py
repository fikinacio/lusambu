import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langgraph.types import Command

import main as m


# ---------------------------------------------------------------------------
# _parse_evolution_webhook — button response
# ---------------------------------------------------------------------------

def test_parse_webhook_buttons_response():
    """buttonsResponseMessage.selectedButtonId é extraído como texto."""
    data = {
        "data": {
            "key": {"fromMe": False, "remoteJid": "244923000000@s.whatsapp.net"},
            "message": {
                "buttonsResponseMessage": {
                    "selectedButtonId": "aprovar",
                    "selectedDisplayText": "✅ Aprovar",
                }
            },
        }
    }
    number, text = m._parse_evolution_webhook(data)
    assert number == "244923000000"
    assert text == "aprovar"


def test_parse_webhook_conversation_takes_priority_over_buttons():
    """conversation tem prioridade sobre buttonsResponseMessage."""
    data = {
        "data": {
            "key": {"fromMe": False, "remoteJid": "244923000000@s.whatsapp.net"},
            "message": {
                "conversation": "olá",
                "buttonsResponseMessage": {"selectedButtonId": "aprovar"},
            },
        }
    }
    number, text = m._parse_evolution_webhook(data)
    assert text == "olá"


def test_parse_webhook_empty_buttons_returns_none():
    """buttonsResponseMessage sem selectedButtonId → (None, None)."""
    data = {
        "data": {
            "key": {"fromMe": False, "remoteJid": "244923000000@s.whatsapp.net"},
            "message": {
                "buttonsResponseMessage": {},
            },
        }
    }
    number, text = m._parse_evolution_webhook(data)
    assert number is None
    assert text is None


# ---------------------------------------------------------------------------
# _resume_proposal_for_fidel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_proposal_no_draft_logs_warning():
    """Sem proposta pendente — função retorna sem chamar o grafo."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=None)), \
         patch.object(m, "proposal_graph", mock_graph):
        await m._resume_proposal_for_fidel("aprovar")
    mock_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_resume_proposal_with_draft_calls_ainvoke():
    """Com proposta pendente — invoca proposal_graph com Command(resume=...)."""
    draft = {"whatsapp": "244923000000", "status": "pending"}
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=draft)), \
         patch.object(m, "proposal_graph", mock_graph):
        await m._resume_proposal_for_fidel("editar")
    mock_graph.ainvoke.assert_called_once()
    call_args = mock_graph.ainvoke.call_args
    command = call_args[0][0]
    assert isinstance(command, Command)
    assert command.resume == "editar"
    assert call_args[1]["config"] == {"configurable": {"thread_id": "proposal-244923000000"}}


@pytest.mark.asyncio
async def test_resume_proposal_graph_exception_is_caught():
    """Excepção no ainvoke é apanhada e logada — não propaga."""
    draft = {"whatsapp": "244923000000", "status": "pending"}
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=draft)), \
         patch.object(m, "proposal_graph", mock_graph):
        await m._resume_proposal_for_fidel("aprovar")  # must not raise


# ---------------------------------------------------------------------------
# _run_proposal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_proposal_calls_ainvoke():
    """_run_proposal invoca proposal_graph com whatsapp inicial e thread correcto."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch.object(m, "proposal_graph", mock_graph):
        await m._run_proposal("244923000000")
    mock_graph.ainvoke.assert_called_once_with(
        {"whatsapp": "244923000000"},
        config={"configurable": {"thread_id": "proposal-244923000000"}},
    )


@pytest.mark.asyncio
async def test_run_proposal_exception_is_caught():
    """Excepção no ainvoke é apanhada — não propaga."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(m, "proposal_graph", mock_graph):
        await m._run_proposal("244923000000")  # must not raise


# ---------------------------------------------------------------------------
# _process_message — Fidel routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_message_routes_fidel_via_router():
    """Mensagem do número do Fidel vai para _route_fidel_message."""
    with patch.object(m, "FIDEL_NUMBER", "41795748225"), \
         patch("main._route_fidel_message", AsyncMock()) as mock_route:
        await m._process_message("41795748225", "aprovar")
    mock_route.assert_called_once_with("aprovar")


@pytest.mark.asyncio
async def test_process_message_non_fidel_does_not_route():
    """Mensagem de outro número não chama _route_fidel_message."""
    mock_graph = MagicMock()
    mock_graph.aget_state = AsyncMock(return_value=MagicMock(values={}))
    mock_graph.ainvoke = AsyncMock()
    with patch.object(m, "FIDEL_NUMBER", "41795748225"), \
         patch.object(m, "graph", mock_graph), \
         patch("main._route_fidel_message", AsyncMock()) as mock_route:
        await m._process_message("244923000000", "olá")
    mock_route.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_empty_fidel_number_no_routing():
    """FIDEL_NUMBER vazio → routing desactivado, mensagem processada normalmente."""
    mock_graph = MagicMock()
    mock_graph.aget_state = AsyncMock(return_value=MagicMock(values={}))
    mock_graph.ainvoke = AsyncMock()
    with patch.object(m, "FIDEL_NUMBER", ""), \
         patch.object(m, "graph", mock_graph), \
         patch("main._route_fidel_message", AsyncMock()) as mock_route:
        await m._process_message("41795748225", "aprovar")
    mock_route.assert_not_called()

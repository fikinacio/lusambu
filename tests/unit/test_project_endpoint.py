import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langgraph.types import Command

import main as m


# ---------------------------------------------------------------------------
# _route_fidel_message — project branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_fidel_project_event_pending():
    """Sem proposta nem factura, mas com event de projecto pendente."""
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_project_event_for_fidel", AsyncMock(return_value={"id": "evt-1"})), \
         patch("main.get_draft_project_for_fidel", AsyncMock(return_value=None)), \
         patch("main._resume_project_for_fidel", AsyncMock()) as mock_project, \
         patch("main._resume_invoice_for_fidel", AsyncMock()) as mock_invoice:
        await m._route_fidel_message("sim")
    mock_project.assert_called_once_with("sim")
    mock_invoice.assert_not_called()


@pytest.mark.asyncio
async def test_route_fidel_draft_project_pending():
    """Sem event, mas com projecto em draft."""
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_project_event_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_draft_project_for_fidel", AsyncMock(return_value={"whatsapp": "244923000000"})), \
         patch("main._resume_project_for_fidel", AsyncMock()) as mock_project:
        await m._route_fidel_message("aprovar")
    mock_project.assert_called_once_with("aprovar")


# ---------------------------------------------------------------------------
# _run_project
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_project_calls_ainvoke():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch.object(m, "project_graph", mock_graph):
        await m._run_project("244923000000")
    mock_graph.ainvoke.assert_called_once_with(
        {"whatsapp": "244923000000"},
        config={"configurable": {"thread_id": "project-244923000000"}},
    )


@pytest.mark.asyncio
async def test_run_project_exception_is_caught():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(m, "project_graph", mock_graph):
        await m._run_project("244923000000")  # must not raise


# ---------------------------------------------------------------------------
# _resume_project_for_fidel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_project_no_event_no_draft_logs_warning():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch("main.get_pending_project_event_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_draft_project_for_fidel", AsyncMock(return_value=None)), \
         patch.object(m, "project_graph", mock_graph):
        await m._resume_project_for_fidel("sim")
    mock_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_resume_project_with_draft_calls_ainvoke():
    draft = {"whatsapp": "244923000000", "status": "draft"}
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch("main.get_pending_project_event_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_draft_project_for_fidel", AsyncMock(return_value=draft)), \
         patch.object(m, "project_graph", mock_graph):
        await m._resume_project_for_fidel("aprovar")
    mock_graph.ainvoke.assert_called_once()
    cmd = mock_graph.ainvoke.call_args[0][0]
    assert isinstance(cmd, Command)
    assert cmd.resume == "aprovar"


@pytest.mark.asyncio
async def test_resume_project_with_event_calls_handler():
    event = {"id": "evt-1", "event_type": "milestone_done", "project_id": "proj-1"}
    with patch("main.get_pending_project_event_for_fidel", AsyncMock(return_value=event)), \
         patch("main._handle_project_event_response", AsyncMock()) as mock_handler:
        await m._resume_project_for_fidel("sim")
    mock_handler.assert_called_once_with(event, "sim")


# ---------------------------------------------------------------------------
# _handle_project_event_response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_event_milestone_done_confirmed_notifies_client():
    event = {
        "id": "evt-1", "event_type": "milestone_done", "project_id": "proj-1",
        "whatsapp": "244923000000", "notion_page_id": "page-abc",
        "contact_name": "Joao", "empresa": "Acme",
        "event_data": {"milestone_nome": "Kickoff"},
    }
    with patch("main.send_whatsapp_message", AsyncMock(return_value=True)) as mock_wa, \
         patch("main.notion_add_log", AsyncMock(return_value=True)), \
         patch("main.update_project_event", AsyncMock()) as mock_evt:
        await m._handle_project_event_response(event, "sim")
    mock_wa.assert_called_once()
    assert "Kickoff" in mock_wa.call_args[0][1]
    mock_evt.assert_called_once_with("evt-1", {"status": "confirmed"})


@pytest.mark.asyncio
async def test_handle_event_not_confirmed_dismisses():
    event = {
        "id": "evt-1", "event_type": "milestone_done", "project_id": "proj-1",
        "whatsapp": "244923000000", "notion_page_id": "page-abc",
        "contact_name": "Joao", "empresa": "Acme",
        "event_data": {"milestone_nome": "Kickoff"},
    }
    with patch("main.send_whatsapp_message", AsyncMock()) as mock_wa, \
         patch("main.update_project_event", AsyncMock()) as mock_evt:
        await m._handle_project_event_response(event, "nao quero")
    mock_wa.assert_not_called()
    mock_evt.assert_called_once_with("evt-1", {"status": "dismissed"})


@pytest.mark.asyncio
async def test_handle_event_completion_confirmed_marks_done():
    event = {
        "id": "evt-1", "event_type": "completion", "project_id": "proj-1",
        "whatsapp": "244923000000", "notion_page_id": "page-abc",
        "contact_name": "Joao", "empresa": "Acme",
    }
    with patch("main.send_whatsapp_message", AsyncMock(return_value=True)) as mock_wa, \
         patch("main.update_project", AsyncMock()) as mock_proj, \
         patch("main.update_project_page_status", AsyncMock(return_value=True)), \
         patch("main.notion_add_log", AsyncMock(return_value=True)), \
         patch("main.update_project_event", AsyncMock()) as mock_evt:
        await m._handle_project_event_response(event, "sim")
    mock_wa.assert_called_once()
    mock_proj.assert_called_once()
    assert mock_proj.call_args[0][0] == "proj-1"
    assert mock_proj.call_args[0][1]["status"] == "concluido"
    mock_evt.assert_called_once_with("evt-1", {"status": "confirmed"})


# ---------------------------------------------------------------------------
# _check_project_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_project_events_delayed_milestone_alerts_fidel():
    delayed = [{"id": "ms-1", "nome": "Kickoff", "data_prevista": "2026-05-01", "empresa": "Acme"}]
    with patch("main.get_delayed_milestones", AsyncMock(return_value=delayed)), \
         patch("main.get_completed_milestones_pending_confirmation", AsyncMock(return_value=[])), \
         patch("main.send_whatsapp_message", AsyncMock(return_value=True)) as mock_wa, \
         patch("main.update_milestone", AsyncMock()) as mock_ms, \
         patch.object(m, "FIDEL_NUMBER", "41795748225"):
        # patch the db query in _check_project_events for the completion check
        from integrations.supabase_client import get_supabase
        with patch("integrations.supabase_client.get_supabase") as mock_db:
            mock_table = MagicMock()
            mock_table.select.return_value = mock_table
            mock_table.eq.return_value = mock_table
            mock_table.execute.return_value = MagicMock(data=[])
            mock_db.return_value.table.return_value = mock_table
            await m._check_project_events()
    mock_wa.assert_called()
    assert "Acme" in mock_wa.call_args[0][1]
    mock_ms.assert_called_once_with("ms-1", {"status": "atrasado"})

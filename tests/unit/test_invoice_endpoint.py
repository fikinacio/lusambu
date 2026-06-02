import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langgraph.types import Command

import main as m


# ---------------------------------------------------------------------------
# _route_fidel_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_fidel_proposal_pending():
    """Proposta pendente → chama _resume_proposal_for_fidel."""
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value={"whatsapp": "244923000000"})), \
         patch("main._resume_proposal_for_fidel", AsyncMock()) as mock_proposal, \
         patch("main._resume_invoice_for_fidel", AsyncMock()) as mock_invoice:
        await m._route_fidel_message("aprovar")
    mock_proposal.assert_called_once_with("aprovar")
    mock_invoice.assert_not_called()


@pytest.mark.asyncio
async def test_route_fidel_invoice_pending():
    """Sem proposta pendente, factura pendente → chama _resume_invoice_for_fidel."""
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value={"whatsapp": "244923000000"})), \
         patch("main._resume_proposal_for_fidel", AsyncMock()) as mock_proposal, \
         patch("main._resume_invoice_for_fidel", AsyncMock()) as mock_invoice:
        await m._route_fidel_message("1")
    mock_proposal.assert_not_called()
    mock_invoice.assert_called_once_with("1")


@pytest.mark.asyncio
async def test_route_fidel_nothing_pending():
    """Sem proposta, factura nem evento de projecto → nenhuma função chamada."""
    with patch("main.get_pending_proposal_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_pending_project_event_for_fidel", AsyncMock(return_value=None)), \
         patch("main.get_draft_project_for_fidel", AsyncMock(return_value=None)), \
         patch("main._resume_proposal_for_fidel", AsyncMock()) as mock_proposal, \
         patch("main._resume_invoice_for_fidel", AsyncMock()) as mock_invoice, \
         patch("main._resume_project_for_fidel", AsyncMock()) as mock_project:
        await m._route_fidel_message("aprovar")
    mock_proposal.assert_not_called()
    mock_invoice.assert_not_called()
    mock_project.assert_not_called()


# ---------------------------------------------------------------------------
# _run_invoice
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_invoice_calls_ainvoke():
    """_run_invoice invoca invoice_graph com whatsapp e thread correcto."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch.object(m, "invoice_graph", mock_graph):
        await m._run_invoice("244923000000")
    mock_graph.ainvoke.assert_called_once_with(
        {"whatsapp": "244923000000"},
        config={"configurable": {"thread_id": "invoice-244923000000"}},
    )


@pytest.mark.asyncio
async def test_run_invoice_exception_is_caught():
    """Excepção no ainvoke é apanhada — não propaga."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(m, "invoice_graph", mock_graph):
        await m._run_invoice("244923000000")  # must not raise


# ---------------------------------------------------------------------------
# _resume_invoice_for_fidel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_invoice_no_draft_logs_warning():
    """Sem factura pendente — função retorna sem chamar o grafo."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value=None)), \
         patch.object(m, "invoice_graph", mock_graph):
        await m._resume_invoice_for_fidel("aprovar")
    mock_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_resume_invoice_with_draft_calls_ainvoke():
    """Com factura pendente — invoca invoice_graph com Command(resume=...)."""
    draft = {"whatsapp": "244923000000", "status": "pending"}
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()
    with patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value=draft)), \
         patch.object(m, "invoice_graph", mock_graph):
        await m._resume_invoice_for_fidel("editar")
    mock_graph.ainvoke.assert_called_once()
    call_args = mock_graph.ainvoke.call_args
    command = call_args[0][0]
    assert isinstance(command, Command)
    assert command.resume == "editar"
    assert call_args[1]["config"] == {"configurable": {"thread_id": "invoice-244923000000"}}


@pytest.mark.asyncio
async def test_resume_invoice_exception_is_caught():
    """Excepção no ainvoke é apanhada — não propaga."""
    draft = {"whatsapp": "244923000000", "status": "pending"}
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("main.get_pending_invoice_for_fidel", AsyncMock(return_value=draft)), \
         patch.object(m, "invoice_graph", mock_graph):
        await m._resume_invoice_for_fidel("aprovar")  # must not raise


# ---------------------------------------------------------------------------
# _check_payment_alerts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_payment_alerts_7d_sends_whatsapp():
    """7 dias → mensagem ao Fidel + marca fidel_alerted_7d=True."""
    inv = {"id": "uuid-1", "empresa": "Acme", "invoice_number": "0001", "invoice_id": "inv-001"}
    with patch("main.get_overdue_invoices", AsyncMock(side_effect=[[inv], []])), \
         patch("main.send_whatsapp_message", AsyncMock(return_value=True)) as mock_wa, \
         patch("main.update_invoice_draft", AsyncMock()) as mock_update, \
         patch.object(m, "FIDEL_NUMBER", "41795748225"):
        await m._check_payment_alerts()
    mock_wa.assert_called_once()
    assert "Acme" in mock_wa.call_args[0][1]
    mock_update.assert_called_once_with("uuid-1", {"fidel_alerted_7d": True})


@pytest.mark.asyncio
async def test_check_payment_alerts_14d_sends_reminder():
    """14 dias → reminder ao cliente + marca client_alerted_14d=True."""
    inv = {"id": "uuid-2", "empresa": "Acme", "invoice_number": "0002", "invoice_id": "inv-002"}
    with patch("main.get_overdue_invoices", AsyncMock(side_effect=[[], [inv]])), \
         patch("main.send_whatsapp_message", AsyncMock(return_value=True)), \
         patch("main.send_invoice_reminder", AsyncMock(return_value=True)) as mock_reminder, \
         patch("main.update_invoice_draft", AsyncMock()) as mock_update:
        await m._check_payment_alerts()
    mock_reminder.assert_called_once_with("inv-002")
    mock_update.assert_called_once_with("uuid-2", {"client_alerted_14d": True})

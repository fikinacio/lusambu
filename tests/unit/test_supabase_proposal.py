import pytest
from unittest.mock import patch, MagicMock
import integrations.supabase_client as sb


def _mock_db(data):
    """Helper: cria mock do Supabase client."""
    mock_result = MagicMock()
    mock_result.data = data
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.in_.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.order.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = mock_result
    mock_db = MagicMock()
    mock_db.table.return_value = mock_table
    return mock_db


@pytest.mark.asyncio
async def test_get_company_config_returns_dict():
    rows = [
        {"key": "company_name", "value": "BISCA MAIS"},
        {"key": "nif", "value": "003378815UE037"},
    ]
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db(rows)):
        result = await sb.get_company_config()
    assert result["company_name"] == "BISCA MAIS"
    assert result["nif"] == "003378815UE037"


@pytest.mark.asyncio
async def test_get_company_config_empty():
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db([])):
        result = await sb.get_company_config()
    assert result == {}


@pytest.mark.asyncio
async def test_get_lead_for_proposal_found():
    lead_row = [{"whatsapp": "244923000000", "company": "Acme", "sector": "retail",
                 "pain_point": "sem clientes", "notas_sales": "quer CRM",
                 "valor_negociado": "250000 Kz"}]
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db(lead_row)):
        result = await sb.get_lead_for_proposal("244923000000")
    assert result is not None
    assert result["company"] == "Acme"


@pytest.mark.asyncio
async def test_get_lead_for_proposal_not_found():
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db([])):
        result = await sb.get_lead_for_proposal("244923000000")
    assert result is None


@pytest.mark.asyncio
async def test_save_proposal_draft_returns_id():
    draft_row = [{"id": "uuid-1234"}]
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db(draft_row)):
        result = await sb.save_proposal_draft({
            "whatsapp": "244923000000",
            "empresa": "Acme",
            "proposal_text": "Texto...",
        })
    assert result == "uuid-1234"


@pytest.mark.asyncio
async def test_update_proposal_draft_no_exception():
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db([])):
        # Should not raise
        await sb.update_proposal_draft("uuid-1234", {"status": "approved"})


@pytest.mark.asyncio
async def test_get_pending_proposal_for_fidel_found():
    rows = [{"id": "uuid-1234", "whatsapp": "244923000000", "status": "pending",
             "proposal_text": "Texto...", "empresa": "Acme"}]
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db(rows)):
        result = await sb.get_pending_proposal_for_fidel()
    assert result is not None
    assert result["id"] == "uuid-1234"


@pytest.mark.asyncio
async def test_get_pending_proposal_for_fidel_none():
    with patch("integrations.supabase_client.get_supabase", return_value=_mock_db([])):
        result = await sb.get_pending_proposal_for_fidel()
    assert result is None

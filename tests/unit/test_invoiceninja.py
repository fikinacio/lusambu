import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from integrations.invoiceninja import (
    _parse_valor,
    get_or_create_client,
    create_invoice,
    send_invoice_email,
    send_invoice_reminder,
)


# ---------------------------------------------------------------------------
# _parse_valor
# ---------------------------------------------------------------------------

def test_parse_valor_dot_thousands():
    assert _parse_valor("250.000 Kz/mês") == 250000.0

def test_parse_valor_comma_decimal():
    assert _parse_valor("2.500,50 Kz") == 2500.50

def test_parse_valor_plain():
    assert _parse_valor("250000") == 250000.0

def test_parse_valor_invalid():
    assert _parse_valor("sem valor") == 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(response_json=None, status_code=200, raise_exc=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = response_json or {}
    if raise_exc:
        mock_resp.raise_for_status.side_effect = raise_exc
    else:
        mock_resp.raise_for_status.return_value = None

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.post = AsyncMock(return_value=mock_resp)
    return mock_client


# ---------------------------------------------------------------------------
# get_or_create_client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_client_exists():
    """Cliente encontrado → devolve id sem criar."""
    mock_cli = _mock_client(response_json={"data": [{"id": "client-abc"}]})
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await get_or_create_client("Acme", "acme@example.com")
    assert result == "client-abc"
    mock_cli.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_client_not_found_creates():
    """Cliente não encontrado → cria e devolve novo id."""
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"data": []}  # empty → create

    post_resp = MagicMock()
    post_resp.raise_for_status.return_value = None
    post_resp.json.return_value = {"data": {"id": "client-new"}}

    mock_cli = AsyncMock()
    mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
    mock_cli.__aexit__ = AsyncMock(return_value=False)
    mock_cli.get = AsyncMock(return_value=get_resp)
    mock_cli.post = AsyncMock(return_value=post_resp)

    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await get_or_create_client("Acme", "acme@example.com")
    assert result == "client-new"
    mock_cli.post.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_client_http_error_propagates():
    """HTTPStatusError na pesquisa propaga-se."""
    err = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock())
    mock_cli = _mock_client(raise_exc=err)
    with patch("httpx.AsyncClient", return_value=mock_cli):
        with pytest.raises(httpx.HTTPStatusError):
            await get_or_create_client("Acme", "acme@example.com")


# ---------------------------------------------------------------------------
# create_invoice
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invoice_success():
    """Factura criada → devolve invoice_id e invoice_number."""
    mock_cli = _mock_client(response_json={"data": {"id": "inv-001", "number": "0001"}})
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await create_invoice("client-abc", "250.000 Kz/mês", "Acme")
    assert result["invoice_id"] == "inv-001"
    assert result["invoice_number"] == "0001"


@pytest.mark.asyncio
async def test_create_invoice_http_error_propagates():
    """HTTPStatusError propaga-se."""
    err = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock())
    mock_cli = _mock_client(raise_exc=err)
    with patch("httpx.AsyncClient", return_value=mock_cli):
        with pytest.raises(httpx.HTTPStatusError):
            await create_invoice("client-abc", "250.000 Kz/mês", "Acme")


# ---------------------------------------------------------------------------
# send_invoice_email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_invoice_email_success():
    mock_cli = _mock_client()
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await send_invoice_email("inv-001")
    assert result is True


@pytest.mark.asyncio
async def test_send_invoice_email_http_error():
    err = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock())
    mock_cli = _mock_client(raise_exc=err)
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await send_invoice_email("inv-001")
    assert result is False


@pytest.mark.asyncio
async def test_send_invoice_email_generic_exception():
    mock_cli = AsyncMock()
    mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
    mock_cli.__aexit__ = AsyncMock(return_value=False)
    mock_cli.post = AsyncMock(side_effect=Exception("timeout"))
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await send_invoice_email("inv-001")
    assert result is False


# ---------------------------------------------------------------------------
# send_invoice_reminder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_invoice_reminder_success():
    mock_cli = _mock_client()
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await send_invoice_reminder("inv-001")
    assert result is True


@pytest.mark.asyncio
async def test_send_invoice_reminder_http_error():
    err = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock())
    mock_cli = _mock_client(raise_exc=err)
    with patch("httpx.AsyncClient", return_value=mock_cli):
        result = await send_invoice_reminder("inv-001")
    assert result is False

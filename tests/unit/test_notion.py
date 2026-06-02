import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from integrations.notion import (
    create_project_page,
    update_project_page_status,
    add_communication_log,
    add_milestone_update,
)


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
    mock_client.patch = AsyncMock(return_value=mock_resp)
    return mock_client


# ---------------------------------------------------------------------------
# create_project_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_project_page_success():
    mock_cli = _mock_client(response_json={'id': 'page-abc'})
    with patch('httpx.AsyncClient', return_value=mock_cli):
        result = await create_project_page({
            'empresa': 'Acme', 'servico_tipo': 'Chatbots & Assistentes IA',
            'contact_name': 'João', 'milestones': [],
        })
    assert result == 'page-abc'
    mock_cli.post.assert_called_once()


@pytest.mark.asyncio
async def test_create_project_page_http_error_propagates():
    err = httpx.HTTPStatusError('err', request=MagicMock(), response=MagicMock())
    mock_cli = _mock_client(raise_exc=err)
    with patch('httpx.AsyncClient', return_value=mock_cli):
        with pytest.raises(httpx.HTTPStatusError):
            await create_project_page({'empresa': 'Acme', 'servico_tipo': 'X'})


# ---------------------------------------------------------------------------
# update_project_page_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_project_page_status_success():
    mock_cli = _mock_client()
    with patch('httpx.AsyncClient', return_value=mock_cli):
        result = await update_project_page_status('page-abc', 'Concluido')
    assert result is True
    mock_cli.patch.assert_called_once()


@pytest.mark.asyncio
async def test_update_project_page_status_http_error():
    err = httpx.HTTPStatusError('err', request=MagicMock(), response=MagicMock())
    mock_cli = _mock_client(raise_exc=err)
    with patch('httpx.AsyncClient', return_value=mock_cli):
        result = await update_project_page_status('page-abc', 'Concluido')
    assert result is False


# ---------------------------------------------------------------------------
# add_communication_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_communication_log_success():
    mock_cli = _mock_client()
    with patch('httpx.AsyncClient', return_value=mock_cli):
        result = await add_communication_log('page-abc', 'Mensagem enviada.')
    assert result is True


@pytest.mark.asyncio
async def test_add_communication_log_exception():
    mock_cli = AsyncMock()
    mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
    mock_cli.__aexit__ = AsyncMock(return_value=False)
    mock_cli.patch = AsyncMock(side_effect=Exception('timeout'))
    with patch('httpx.AsyncClient', return_value=mock_cli):
        result = await add_communication_log('page-abc', 'Mensagem.')
    assert result is False


# ---------------------------------------------------------------------------
# add_milestone_update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_milestone_update_success():
    mock_cli = _mock_client()
    with patch('httpx.AsyncClient', return_value=mock_cli):
        result = await add_milestone_update('page-abc', 'Kickoff', 'concluido')
    assert result is True

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
import integrations.evolution as evo


@pytest.mark.asyncio
async def test_send_button_message_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await evo.send_button_message(
            number="41795748225",
            body_text="Proposta para Acme",
            buttons=[
                {"buttonId": "aprovar", "buttonText": {"displayText": "✅ Aprovar"}, "type": 1},
            ],
            footer="Fidel Kussunga | Bisca+",
        )
    assert result is True


@pytest.mark.asyncio
async def test_send_button_message_failure():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("network error"))
        mock_client_cls.return_value = mock_client

        result = await evo.send_button_message("123", "body", [], "footer")
    assert result is False


@pytest.mark.asyncio
async def test_send_media_message_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await evo.send_media_message(
            number="41795748225",
            media_url="https://example.com/logo.png",
            mediatype="image",
            caption="BISCA+",
        )
    assert result is True


@pytest.mark.asyncio
async def test_send_media_message_failure():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("timeout"))
        mock_client_cls.return_value = mock_client

        result = await evo.send_media_message("123", "https://x.com/img.png")
    assert result is False


@pytest.mark.asyncio
async def test_send_button_message_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403", request=MagicMock(), response=mock_resp
    )
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        result = await evo.send_button_message("123", "body", [])
    assert result is False


@pytest.mark.asyncio
async def test_send_media_message_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=mock_resp
    )
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        result = await evo.send_media_message("123", "https://x.com/img.png")
    assert result is False

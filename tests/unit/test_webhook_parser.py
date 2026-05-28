"""
Testes unitários de _parse_evolution_webhook — extrai (número, texto) da payload
da Evolution API. Cobre os formatos de mensagem reais da API.
"""
import pytest
from main import _parse_evolution_webhook


def _payload(remote_jid: str, from_me: bool, text: str | None = None, extended: str | None = None) -> dict:
    """Helper para construir payloads de teste."""
    message = {}
    if text is not None:
        message["conversation"] = text
    if extended is not None:
        message["extendedTextMessage"] = {"text": extended}
    return {
        "data": {
            "key": {"fromMe": from_me, "remoteJid": remote_jid},
            "message": message,
        }
    }


# ---------------------------------------------------------------------------
# Casos válidos
# ---------------------------------------------------------------------------

def test_mensagem_texto_simples():
    number, text = _parse_evolution_webhook(
        _payload("244923111111@s.whatsapp.net", False, text="Olá, vi o anúncio")
    )
    assert number == "244923111111"
    assert text == "Olá, vi o anúncio"


def test_mensagem_extendida():
    """extendedTextMessage é usado em mensagens com formatação/links."""
    number, text = _parse_evolution_webhook(
        _payload("244923222222@s.whatsapp.net", False, extended="Mensagem com *bold*")
    )
    assert number == "244923222222"
    assert text == "Mensagem com *bold*"


def test_texto_simples_tem_prioridade_sobre_extendido():
    """conversation prevalece sobre extendedTextMessage."""
    data = {
        "data": {
            "key": {"fromMe": False, "remoteJid": "244923333333@s.whatsapp.net"},
            "message": {
                "conversation": "Texto simples",
                "extendedTextMessage": {"text": "Texto extendido"},
            },
        }
    }
    number, text = _parse_evolution_webhook(data)
    assert text == "Texto simples"


def test_remove_sufixo_whatsapp_net():
    number, _ = _parse_evolution_webhook(
        _payload("244923444444@s.whatsapp.net", False, text="Olá")
    )
    assert number == "244923444444"


def test_remove_sufixo_grupo():
    number, _ = _parse_evolution_webhook(
        _payload("123456789@g.us", False, text="Mensagem de grupo")
    )
    assert number == "123456789"


def test_remove_device_id_meta_linked():
    """Contas WhatsApp ligadas ao Facebook/Meta enviam remoteJid com device ID.
    Ex: '244923456789:7@s.whatsapp.net' → deve extrair '244923456789'.
    Sem este fix o número fica '244923456789:7' e a resposta nunca é entregue."""
    number, text = _parse_evolution_webhook(
        _payload("244923456789:7@s.whatsapp.net", False, text="Olá, vi o anúncio no Facebook")
    )
    assert number == "244923456789"
    assert text == "Olá, vi o anúncio no Facebook"


def test_texto_com_espacos_e_removido():
    _, text = _parse_evolution_webhook(
        _payload("244923111111@s.whatsapp.net", False, text="  Olá  ")
    )
    assert text == "Olá"


# ---------------------------------------------------------------------------
# Casos ignorados (devolvem None, None)
# ---------------------------------------------------------------------------

def test_mensagem_do_proprio_bot_ignorada():
    number, text = _parse_evolution_webhook(
        _payload("244923111111@s.whatsapp.net", True, text="Mensagem do bot")
    )
    assert number is None
    assert text is None


def test_mensagem_sem_texto_ignorada():
    number, text = _parse_evolution_webhook(
        _payload("244923111111@s.whatsapp.net", False)
    )
    assert number is None
    assert text is None


def test_payload_vazio_ignorado():
    number, text = _parse_evolution_webhook({})
    assert number is None
    assert text is None


def test_payload_sem_data_ignorado():
    number, text = _parse_evolution_webhook({"event": "MESSAGES_UPSERT"})
    assert number is None
    assert text is None


def test_payload_sem_numero_ignorado():
    data = {
        "data": {
            "key": {"fromMe": False, "remoteJid": ""},
            "message": {"conversation": "Olá"},
        }
    }
    number, text = _parse_evolution_webhook(data)
    assert number is None
    assert text is None

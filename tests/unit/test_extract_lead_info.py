"""
Testes unitários de _extract_lead_info — chama o LLM e faz parse do JSON resultante.
LLM é sempre mockado: testamos a lógica de parse e o fallback de erro.
"""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage

from agent.nodes import _extract_lead_info


def _mock_extractor(json_text: str):
    """Devolve um mock do llm_extractor que responde com json_text."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value=AIMessage(content=json_text))
    return mock


# ---------------------------------------------------------------------------
# Parse correcto
# ---------------------------------------------------------------------------

async def test_extrai_lead_com_empresa():
    json_resp = '{"name": "João", "has_business": true, "company": "Loja Luanda", "sector": "Comércio", "pain_point": "Atendimento lento", "size": "10 pessoas", "classification": "warm", "is_objecting": false, "wants_human": false, "ready_to_close": false}'
    with patch("agent.nodes.llm_extractor", _mock_extractor(json_resp)):
        result = await _extract_lead_info([HumanMessage(content="Tenho uma loja em Luanda")])

    assert result["has_business"] is True
    assert result["company"] == "Loja Luanda"
    assert result["sector"] == "Comércio"
    assert result["classification"] == "warm"
    assert result["is_objecting"] is False


async def test_extrai_lead_sem_empresa():
    json_resp = '{"name": null, "has_business": false, "company": null, "sector": null, "pain_point": null, "size": null, "classification": "unknown", "is_objecting": false, "wants_human": false, "ready_to_close": false}'
    with patch("agent.nodes.llm_extractor", _mock_extractor(json_resp)):
        result = await _extract_lead_info([HumanMessage(content="Não tenho empresa")])

    assert result["has_business"] is False
    assert result["classification"] == "unknown"


async def test_extrai_lead_quer_humano():
    json_resp = '{"has_business": true, "wants_human": true, "is_objecting": false, "ready_to_close": false, "classification": "warm", "name": null, "company": null, "sector": null, "pain_point": null, "size": null}'
    with patch("agent.nodes.llm_extractor", _mock_extractor(json_resp)):
        result = await _extract_lead_info([HumanMessage(content="Quero falar com um humano")])

    assert result["wants_human"] is True


async def test_extrai_lead_hot():
    json_resp = '{"has_business": true, "sector": "Imobiliária", "pain_point": "Qualificação de leads", "classification": "hot", "is_objecting": false, "wants_human": false, "ready_to_close": true, "name": "Ana", "company": "Imob SA", "size": "5"}'
    with patch("agent.nodes.llm_extractor", _mock_extractor(json_resp)):
        result = await _extract_lead_info([HumanMessage(content="Quero avançar")])

    assert result["classification"] == "hot"
    assert result["ready_to_close"] is True


# ---------------------------------------------------------------------------
# Fallback de erro — LLM devolve texto inválido
# ---------------------------------------------------------------------------

async def test_fallback_quando_json_invalido():
    """Se o LLM devolver texto que não é JSON, deve retornar valores seguros."""
    with patch("agent.nodes.llm_extractor", _mock_extractor("Desculpe, não entendi.")):
        result = await _extract_lead_info([HumanMessage(content="Olá")])

    assert result["has_business"] is None
    assert result["classification"] == "unknown"
    assert result["is_objecting"] is False
    assert result["wants_human"] is False
    assert result["ready_to_close"] is False


async def test_fallback_quando_llm_lanca_excecao():
    """Se o LLM falhar completamente, não deve propagar a excepção."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(side_effect=Exception("API timeout"))

    with patch("agent.nodes.llm_extractor", mock):
        result = await _extract_lead_info([HumanMessage(content="Olá")])

    assert result["classification"] == "unknown"
    assert result["wants_human"] is False


async def test_fallback_quando_json_sem_campos_obrigatorios():
    """JSON válido mas incompleto — campos ausentes não devem crashar o código."""
    with patch("agent.nodes.llm_extractor", _mock_extractor('{"classification": "cold"}')):
        result = await _extract_lead_info([HumanMessage(content="Olá")])

    assert result["classification"] == "cold"
    # Campos ausentes devolvem None via .get()
    assert result.get("has_business") is None

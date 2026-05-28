"""
Testes unitários do supervisor_node.
Verifica as três decisões possíveis e o comportamento de fallback.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from sales_agent.supervisor import supervisor_node


def _supervisor_response(estado: str, razao: str = "teste", dor: str = None) -> AIMessage:
    payload = {
        "estado": estado,
        "razao": razao,
        "dor_confirmada": dor,
        "decisor_confirmado": estado != "continua_qualificacao",
    }
    if estado == "escala_para_fidel":
        payload["resumo_para_fidel"] = "Resumo para Fidel"
    return AIMessage(content=json.dumps(payload))


def _base_state(**overrides) -> dict:
    state = {
        "messages": [HumanMessage(content="Olá")],
        "whatsapp_number": "244923999",
        "stage": "pitch",
        "supervisor_decision": {},
        "sales_agent_active": False,
        "escalation_reason": "",
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Decisão: continua_qualificacao
# ---------------------------------------------------------------------------

async def test_continua_qualificacao_quando_conversa_inicial():
    with patch("sales_agent.supervisor.llm_supervisor") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_supervisor_response("continua_qualificacao"))

        result = await supervisor_node(_base_state(
            messages=[HumanMessage(content="Olá, vi o vosso anúncio")],
            stage="qualify",
        ))

    assert result["supervisor_decision"]["estado"] == "continua_qualificacao"
    assert result["sales_agent_active"] is False
    assert result["escalation_reason"] == ""


# ---------------------------------------------------------------------------
# Decisão: passa_para_sales
# ---------------------------------------------------------------------------

async def test_passa_para_sales_activa_flag():
    with patch("sales_agent.supervisor.llm_supervisor") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_supervisor_response(
            "passa_para_sales",
            razao="Dor confirmada, decisor identificado, pediu preço",
            dor="Leads perdidos fora de horário",
        ))

        result = await supervisor_node(_base_state(
            messages=[
                HumanMessage(content="Sou dono de um stand, perdemos clientes à noite"),
                AIMessage(content="Entendo. Quanto perde por mês com isso?"),
                HumanMessage(content="Muito. Quanto custa a vossa solução?"),
            ],
        ))

    assert result["supervisor_decision"]["estado"] == "passa_para_sales"
    assert result["sales_agent_active"] is True
    assert result["supervisor_decision"]["dor_confirmada"] == "Leads perdidos fora de horário"


async def test_flag_permanece_activa_se_ja_estava():
    """Uma vez activo, o Sales Agent mantém controlo mesmo que supervisor avalie diferente."""
    with patch("sales_agent.supervisor.llm_supervisor") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_supervisor_response("continua_qualificacao"))

        result = await supervisor_node(_base_state(sales_agent_active=True))

    assert result["sales_agent_active"] is True


# ---------------------------------------------------------------------------
# Decisão: escala_para_fidel
# ---------------------------------------------------------------------------

async def test_escala_para_fidel_define_razao():
    razao = "Setup acima de 300.000 AOA mencionado"
    with patch("sales_agent.supervisor.llm_supervisor") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_supervisor_response(
            "escala_para_fidel", razao=razao,
        ))

        result = await supervisor_node(_base_state(
            messages=[HumanMessage(content="Queremos automação para 5 departamentos, ~350.000 AOA")],
        ))

    assert result["supervisor_decision"]["estado"] == "escala_para_fidel"
    assert result["escalation_reason"] == razao
    assert result["sales_agent_active"] is False


# ---------------------------------------------------------------------------
# Fallback: JSON inválido
# ---------------------------------------------------------------------------

async def test_json_invalido_faz_fallback_para_qualificacao():
    with patch("sales_agent.supervisor.llm_supervisor") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="resposta inesperada sem JSON"))

        result = await supervisor_node(_base_state())

    assert result["supervisor_decision"]["estado"] == "continua_qualificacao"
    assert result["sales_agent_active"] is False


async def test_excecao_llm_faz_fallback_para_qualificacao():
    with patch("sales_agent.supervisor.llm_supervisor") as mock_llm:
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("Timeout"))

        result = await supervisor_node(_base_state())

    assert result["supervisor_decision"]["estado"] == "continua_qualificacao"
    assert result["sales_agent_active"] is False

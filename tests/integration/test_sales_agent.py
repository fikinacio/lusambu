"""
Integração: fluxo completo do Sales Agent.
Quatro cenários: activação, resposta, escalada via supervisor, escalada por desconto.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

from agent.graph import create_graph


@pytest.fixture
def grafo():
    return create_graph(MemorySaver())


# ---------------------------------------------------------------------------
# Fixtures de resposta LLM
# ---------------------------------------------------------------------------

def _lusambu_extractor_pitch() -> AIMessage:
    return AIMessage(content=(
        '{"name": "Marco", "has_business": true, "company": "AutoAO", "sector": "Automóvel", '
        '"pain_point": "Leads perdidos fora de horário", "size": "5", "classification": "hot", '
        '"is_objecting": false, "wants_human": false, "ready_to_close": false}'
    ))


def _supervisor_passa_para_sales() -> AIMessage:
    return AIMessage(content=json.dumps({
        "estado": "passa_para_sales",
        "razao": "Dor confirmada, decisor identificado, pediu preço",
        "dor_confirmada": "Leads perdidos fora de horário",
        "decisor_confirmado": True,
    }))


def _supervisor_escala_fidel() -> AIMessage:
    return AIMessage(content=json.dumps({
        "estado": "escala_para_fidel",
        "razao": "Setup acima do threshold mencionado pelo lead",
        "dor_confirmada": "Automação empresarial",
        "decisor_confirmado": True,
        "resumo_para_fidel": "Lead quer solução enterprise acima de 300.000 AOA",
    }))


# ---------------------------------------------------------------------------
# Cenário 1: Supervisor activa Sales Agent na próxima mensagem
# ---------------------------------------------------------------------------

async def test_supervisor_activa_flag_sales_agent(grafo):
    """
    Lead maduro em stage pitch → supervisor decide passa_para_sales.
    Após esta invocação, sales_agent_active=True no estado.
    """
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock), \
         patch("sales_agent.supervisor.llm_supervisor") as mock_supervisor:

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Temos uma solução para o vosso stand."))
        mock_extractor.ainvoke = AsyncMock(return_value=_lusambu_extractor_pitch())
        mock_supervisor.ainvoke = AsyncMock(return_value=_supervisor_passa_para_sales())

        config = {"configurable": {"thread_id": "sales_int_001"}}
        state = {
            "messages": [HumanMessage(content="Quanto custa? Perdemos clientes à noite")],
            "whatsapp_number": "244923301",
            "lead_info": {"has_business": True, "sector": "Automóvel"},
            "stage": "pitch",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
            "supervisor_decision": {},
            "sales_agent_active": False,
        }

        result = await grafo.ainvoke(state, config=config)

    assert result["sales_agent_active"] is True
    assert result["supervisor_decision"]["estado"] == "passa_para_sales"


# ---------------------------------------------------------------------------
# Cenário 2: Sales Agent responde directamente quando activo
# ---------------------------------------------------------------------------

async def test_sales_agent_responde_quando_activo(grafo):
    """
    Dispatcher encaminha directo para Sales Agent.
    Sales Agent usa RAG e envia resposta ao lead.
    """
    sales_response = "Para um stand, temos o assistente 24/7 a 95.000 AOA de setup. Posso enviar a proposta hoje?"

    with patch("sales_agent.sales_node.llm_sales") as mock_sales, \
         patch("sales_agent.sales_node.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("sales_agent.sales_node.send_typing_indicator", new_callable=AsyncMock), \
         patch("sales_agent.sales_node._human_delay", new_callable=AsyncMock), \
         patch("sales_agent.sales_node.consultar_conhecimento", new_callable=AsyncMock) as mock_rag:

        mock_sales.ainvoke = AsyncMock(return_value=AIMessage(content=sales_response))
        mock_rag.return_value = "[PORTFOLIO_PRECO] Assistente RAG: Setup 95.000 AOA + 42.000 AOA/mês"

        config = {"configurable": {"thread_id": "sales_int_002"}}
        state = {
            "messages": [HumanMessage(content="Qual o preço exactamente?")],
            "whatsapp_number": "244923302",
            "lead_info": {"sector": "Automóvel", "pain_point": "Leads perdidos"},
            "stage": "pitch",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
            "supervisor_decision": {"dor_confirmada": "Leads perdidos fora de horário"},
            "sales_agent_active": True,
        }

        result = await grafo.ainvoke(state, config=config)

    # Sales Agent enviou exactamente 1 mensagem
    mock_send.assert_called_once()
    numero, msg = mock_send.call_args[0]
    assert numero == "244923302"
    assert "95.000" in msg or "proposta" in msg.lower()

    # RAG foi consultado
    mock_rag.assert_called_once()


# ---------------------------------------------------------------------------
# Cenário 3: Supervisor escala para Fidel via escalate_node
# ---------------------------------------------------------------------------

async def test_supervisor_escala_fidel_notifica(grafo):
    """
    Supervisor decide escala_para_fidel → escalate_node notifica Fidel.
    """
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.send_typing_indicator", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock), \
         patch("sales_agent.supervisor.llm_supervisor") as mock_supervisor:

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Entendo a vossa necessidade."))
        mock_extractor.ainvoke = AsyncMock(return_value=AIMessage(content=(
            '{"name": "Diogo", "has_business": true, "company": "CorpAO", "sector": "Enterprise", '
            '"pain_point": "Automação completa", "size": "500", "classification": "hot", '
            '"is_objecting": false, "wants_human": false, "ready_to_close": false}'
        )))
        mock_supervisor.ainvoke = AsyncMock(return_value=_supervisor_escala_fidel())

        config = {"configurable": {"thread_id": "sales_int_003"}}
        state = {
            "messages": [HumanMessage(content="Queremos solução para 5 departamentos, à volta de 350.000 AOA")],
            "whatsapp_number": "244923303",
            "lead_info": {},
            "stage": "pitch",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
            "supervisor_decision": {},
            "sales_agent_active": False,
        }

        result = await grafo.ainvoke(state, config=config)

    mock_fidel.assert_called_once()
    fidel_msg = mock_fidel.call_args[0][0]
    assert "244923303" in fidel_msg
    assert result["stage"] == "end"
    assert result["fidel_notified"] is True


# ---------------------------------------------------------------------------
# Cenário 4: Sales Agent detecta desconto excessivo e escala para Fidel
# ---------------------------------------------------------------------------

async def test_sales_agent_escala_desconto_excessivo(grafo):
    """
    Lead pede 20% de desconto → Sales Agent detecta threshold e escala para Fidel.
    Lead recebe mensagem de espera; Fidel recebe notificação.
    """
    with patch("sales_agent.sales_node.send_whatsapp_message", new_callable=AsyncMock) as mock_sales_send, \
         patch("sales_agent.sales_node.send_typing_indicator", new_callable=AsyncMock), \
         patch("sales_agent.sales_node._human_delay", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.send_typing_indicator", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock):

        config = {"configurable": {"thread_id": "sales_int_004"}}
        state = {
            "messages": [HumanMessage(content="Podem fazer um desconto de 20% no setup?")],
            "whatsapp_number": "244923304",
            "lead_info": {"sector": "Automóvel"},
            "stage": "pitch",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
            "supervisor_decision": {"dor_confirmada": "Leads perdidos"},
            "sales_agent_active": True,
        }

        result = await grafo.ainvoke(state, config=config)

    # Sales Agent enviou mensagem de espera ao lead
    mock_sales_send.assert_called_once()
    _, holding_msg = mock_sales_send.call_args[0]
    assert "confirmar" in holding_msg.lower() or "detalhe" in holding_msg.lower()

    # Fidel foi notificado via escalate_node
    mock_fidel.assert_called_once()

    # Conversa encerrada com stage=end
    assert result["stage"] == "end"
    assert result["fidel_notified"] is True


# ---------------------------------------------------------------------------
# Idempotência: Lusambu normal (qualify) não activa o supervisor
# ---------------------------------------------------------------------------

async def test_qualify_stage_nao_activa_supervisor(grafo):
    """
    Stage qualify → supervisor não corre → sales_agent_active permanece False.
    """
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock), \
         patch("sales_agent.supervisor.llm_supervisor") as mock_supervisor:

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Tens alguma empresa?"))
        # Extractor mantém stage=qualify (sem sector ou pain_point)
        mock_extractor.ainvoke = AsyncMock(return_value=AIMessage(content=(
            '{"name": null, "has_business": true, "company": null, "sector": null, '
            '"pain_point": null, "size": null, "classification": "unknown", '
            '"is_objecting": false, "wants_human": false, "ready_to_close": false}'
        )))

        config = {"configurable": {"thread_id": "sales_int_005"}}
        state = {
            "messages": [HumanMessage(content="Olá, vi o vosso anúncio")],
            "whatsapp_number": "244923305",
            "lead_info": {},
            "stage": "qualify",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
            "supervisor_decision": {},
            "sales_agent_active": False,
        }

        result = await grafo.ainvoke(state, config=config)

    # Supervisor não deve ter sido chamado (stage=qualify após lusambu)
    mock_supervisor.ainvoke.assert_not_called()
    assert result.get("sales_agent_active", False) is False

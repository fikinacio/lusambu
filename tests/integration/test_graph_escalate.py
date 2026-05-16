"""
Integração: fluxo completo de escalação.
Três cenários: quer humano, pronto para fechar, objecção repetida.
"""
import pytest
from unittest.mock import AsyncMock, patch
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

from agent.graph import create_graph


@pytest.fixture
def grafo():
    return create_graph(MemorySaver())


def _extractor_quer_humano() -> AIMessage:
    return AIMessage(content=(
        '{"name": "Pedro", "has_business": true, "company": "TechAO", "sector": "Tecnologia", '
        '"pain_point": "Processos manuais", "size": "20", "classification": "warm", '
        '"is_objecting": false, "wants_human": true, "ready_to_close": false}'
    ))


def _extractor_pronto_fechar() -> AIMessage:
    # Lead já indicou nome e horário preferido — _determine_stage escala directamente.
    return AIMessage(content=(
        '{"name": "Ana", "has_business": true, "company": "ImobAO", "sector": "Imobiliária", '
        '"pain_point": "Qualificação lenta", "size": "8", "scheduled_time": "quarta de manhã", '
        '"classification": "hot", "is_objecting": false, "wants_human": false, "ready_to_close": true}'
    ))


def _extractor_com_objeccao() -> AIMessage:
    return AIMessage(content=(
        '{"name": "Carlos", "has_business": true, "company": "DistribAO", "sector": "Distribuição", '
        '"pain_point": "Gestão de encomendas", "size": "15", "classification": "cold", '
        '"is_objecting": true, "wants_human": false, "ready_to_close": false}'
    ))


# ---------------------------------------------------------------------------
# Cenário 1: lead pede humano explicitamente
# ---------------------------------------------------------------------------

async def test_escalacao_por_pedido_de_humano(grafo):
    """
    Lead diz 'quero falar com humano' → wants_human=True → escalate_node.
    Fidel deve ser notificado. Lead deve receber mensagem de transição.
    """
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock) as mock_upsert, \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Claro, já passo ao especialista."))
        mock_extractor.ainvoke = AsyncMock(return_value=_extractor_quer_humano())

        config = {"configurable": {"thread_id": "244923101"}}
        state = {
            "messages": [HumanMessage(content="Quero falar com um humano")],
            "whatsapp_number": "244923101",
            "lead_info": {},
            "stage": "qualify",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
        }

        result = await grafo.ainvoke(state, config=config)

    # Fidel notificado exactamente 1 vez
    mock_fidel.assert_called_once()
    fidel_msg = mock_fidel.call_args[0][0]
    assert "244923101" in fidel_msg
    assert "humano" in fidel_msg.lower() or "Intervenção" in fidel_msg

    # Lead recebe mensagem de transição (enviada pelo escalate_node)
    assert mock_send.call_count == 2
    _, transicao_msg = mock_send.call_args_list[1][0]
    assert "especialista" in transicao_msg.lower()

    # Upsert com status escalado
    ultimo_upsert = mock_upsert.call_args_list[-1][0][0]
    assert ultimo_upsert["status"] == "escalado"

    assert result["fidel_notified"] is True
    assert result["stage"] == "end"


# ---------------------------------------------------------------------------
# Cenário 2: lead pronto para fechar
# ---------------------------------------------------------------------------

async def test_escalacao_por_fecho(grafo):
    """ready_to_close + closing completo (dados confirmados + Calendly enviado) => escala."""
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Óptimo! Vou preparar tudo."))
        mock_extractor.ainvoke = AsyncMock(return_value=_extractor_pronto_fechar())

        config = {"configurable": {"thread_id": "244923102"}}
        state = {
            "messages": [HumanMessage(content="Quero avançar, como fazemos?")],
            "whatsapp_number": "244923102",
            "lead_info": {},
            "stage": "closing",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
            "data_confirmed": True,
            "calendly_sent": True,   # simula que o link já foi enviado em iteração anterior
        }

        result = await grafo.ainvoke(state, config=config)

    mock_fidel.assert_called_once()
    fidel_msg = mock_fidel.call_args[0][0]
    assert "fecho formal" in fidel_msg.lower() or "avançar" in fidel_msg.lower()
    assert result["stage"] == "end"


# ---------------------------------------------------------------------------
# Cenário 3: objecção repetida (objection_count já era 1)
# ---------------------------------------------------------------------------

async def test_escalacao_por_objeccao_repetida(grafo):
    """
    Estado inicial: stage=objection, objection_count=1.
    lusambu_node incrementa para 2 → _determine_stage retorna escalate.
    """
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Compreendo a tua preocupação."))
        mock_extractor.ainvoke = AsyncMock(return_value=_extractor_com_objeccao())

        config = {"configurable": {"thread_id": "244923103"}}
        state = {
            "messages": [HumanMessage(content="É demasiado caro para mim")],
            "whatsapp_number": "244923103",
            "lead_info": {"has_business": True, "sector": "Distribuição"},
            "stage": "objection",
            "objection_count": 1,   # já houve 1 objecção anterior
            "escalation_reason": "",
            "fidel_notified": False,
        }

        result = await grafo.ainvoke(state, config=config)

    mock_fidel.assert_called_once()
    fidel_msg = mock_fidel.call_args[0][0]
    assert "objecção" in fidel_msg.lower() or "Intervenção" in fidel_msg
    assert result["stage"] == "end"


# ---------------------------------------------------------------------------
# Idempotência: escalação não notifica Fidel duas vezes
# ---------------------------------------------------------------------------

async def test_fidel_nao_notificado_duas_vezes(grafo):
    """Se fidel_notified=True já estiver no estado, escalate_node retorna sem fazer nada."""
    with patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        from agent.nodes import escalate_node
        state = {
            "messages": [],
            "whatsapp_number": "244923104",
            "lead_info": {},
            "stage": "escalate",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": True,   # já foi notificado
        }

        result = await escalate_node(state)

    mock_fidel.assert_not_called()
    assert result["stage"] == "end"

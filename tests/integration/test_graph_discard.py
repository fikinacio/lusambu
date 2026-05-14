"""
Integração: fluxo completo de descarte.
Lead sem empresa → lusambu_node responde → discard_node envia despedida → fim.
Redis substituído por MemorySaver. LLM, Evolution API e Supabase são mockados.
"""
import pytest
from unittest.mock import AsyncMock
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

from agent.graph import create_graph


@pytest.fixture
def grafo():
    """Grafo com checkpointer em memória (sem Redis real)."""
    return create_graph(MemorySaver())


def _extractor_sem_empresa() -> AIMessage:
    return AIMessage(content=(
        '{"name": null, "has_business": false, "company": null, "sector": null, '
        '"pain_point": null, "size": null, "classification": "unknown", '
        '"is_objecting": false, "wants_human": false, "ready_to_close": false}'
    ))


async def test_lead_sem_empresa_descartado(grafo):
    """
    Caminho: lusambu_node → discard_node → END
    Verifica: 2 mensagens enviadas, último upsert com status=descartado.
    """
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock), \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock) as mock_upsert, \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Tens alguma empresa?"))
        mock_extractor.ainvoke = AsyncMock(return_value=_extractor_sem_empresa())

        config = {"configurable": {"thread_id": "244923001"}}
        state = {
            "messages": [HumanMessage(content="Não tenho empresa, sou estudante")],
            "whatsapp_number": "244923001",
            "lead_info": {},
            "stage": "qualify",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
        }

        result = await grafo.ainvoke(state, config=config)

    # lusambu_node + discard_node enviam 1 mensagem cada
    assert mock_send.call_count == 2

    # Mensagem de despedida vem do discard_node (segunda chamada)
    numero, goodbye = mock_send.call_args_list[1][0]
    assert numero == "244923001"
    assert "empresa" in goodbye.lower()

    # Último upsert deve marcar como descartado
    ultimo_upsert = mock_upsert.call_args_list[-1][0][0]
    assert ultimo_upsert["status"] == "descartado"
    assert ultimo_upsert["whatsapp"] == "244923001"

    # Stage final
    assert result["stage"] == "end"


async def test_lead_sem_empresa_nao_notifica_fidel(grafo):
    """Descarte não deve notificar Fidel — ele só intervém em escalações."""
    with patch("agent.nodes.llm") as mock_llm, \
         patch("agent.nodes.llm_extractor") as mock_extractor, \
         patch("agent.nodes.send_whatsapp_message", new_callable=AsyncMock), \
         patch("agent.nodes.notify_fidel", new_callable=AsyncMock) as mock_fidel, \
         patch("agent.nodes.upsert_lead", new_callable=AsyncMock), \
         patch("agent.nodes._human_delay", new_callable=AsyncMock):

        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Ok"))
        mock_extractor.ainvoke = AsyncMock(return_value=_extractor_sem_empresa())

        config = {"configurable": {"thread_id": "244923002"}}
        state = {
            "messages": [HumanMessage(content="Sou particular")],
            "whatsapp_number": "244923002",
            "lead_info": {},
            "stage": "qualify",
            "objection_count": 0,
            "escalation_reason": "",
            "fidel_notified": False,
        }

        await grafo.ainvoke(state, config=config)

    mock_fidel.assert_not_called()

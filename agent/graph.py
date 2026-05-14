import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver

from .state import LusambuState
from .nodes import lusambu_node, discard_node, escalate_node

logger = logging.getLogger(__name__)


def _router(state: LusambuState) -> str:
    """
    Decide o próximo nó após lusambu_node.
    Para stages conversacionais (qualify/pitch/objection/close), termina e
    aguarda a próxima mensagem via webhook — o checkpointer Redis preserva
    o estado entretanto.
    """
    stage = state.get("stage", "qualify")

    if stage == "discard":
        return "discard"
    if stage == "escalate":
        return "escalate"

    # qualify | pitch | objection | close → lusambu já respondeu, fim desta invocação
    return END


def create_graph(redis_url: str):
    """
    Constrói e compila o grafo LangGraph do agente Lusambu.
    Usa AsyncRedisSaver para persistir estado por conversa (thread_id = número WhatsApp).
    """
    builder = StateGraph(LusambuState)

    builder.add_node("lusambu", lusambu_node)
    builder.add_node("discard", discard_node)
    builder.add_node("escalate", escalate_node)

    builder.set_entry_point("lusambu")

    builder.add_conditional_edges("lusambu", _router, {
        "discard": "discard",
        "escalate": "escalate",
        END: END,
    })

    builder.add_edge("discard", END)
    builder.add_edge("escalate", END)

    checkpointer = AsyncRedisSaver.from_conn_string(redis_url)
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Grafo Lusambu compilado com sucesso.")
    return graph

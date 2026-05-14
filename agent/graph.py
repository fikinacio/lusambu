import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from .state import LusambuState
from .nodes import lusambu_node, discard_node, escalate_node

logger = logging.getLogger(__name__)


def _router(state: LusambuState) -> str:
    stage = state.get("stage", "qualify")
    if stage == "discard":
        return "discard"
    if stage == "escalate":
        return "escalate"
    return END


def create_graph(checkpointer: BaseCheckpointSaver):
    """
    Constrói e compila o grafo LangGraph.
    O checkpointer (Redis em produção, MemorySaver em testes/local) é passado externamente.
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

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Grafo Lusambu compilado com sucesso.")
    return graph

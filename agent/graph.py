import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from .state import LusambuState
from .nodes import lusambu_node, discard_node, escalate_node
from sales_agent.supervisor import supervisor_node
from sales_agent.sales_node import sales_agent_node

logger = logging.getLogger(__name__)


def _dispatcher_router(state: LusambuState) -> str:
    """Entry point: se Sales Agent está activo, vai directo. Caso contrário, Lusambu."""
    if state.get("sales_agent_active"):
        return "sales_agent"
    return "lusambu"


def _after_lusambu_router(state: LusambuState) -> str:
    """Após Lusambu: descarte/escalada vão directo; stages avançados passam pelo supervisor."""
    stage = state.get("stage", "qualify")
    if stage == "discard":
        return "discard"
    if stage == "escalate":
        return "escalate"
    if stage in ("pitch", "objection", "closing"):
        return "supervisor"
    return END


def _after_supervisor_router(state: LusambuState) -> str:
    """Supervisor decidiu: escalações e encerramento vão para escalate_node; o resto termina."""
    decision = state.get("supervisor_decision", {})
    estado = decision.get("estado", "continua_qualificacao")
    if estado in ("escala_para_fidel", "conversa_encerrada"):
        return "escalate"
    # passa_para_sales: flag já definida no supervisor_node; Sales Agent entra na PRÓXIMA mensagem
    return END


def _after_sales_router(state: LusambuState) -> str:
    """Sales Agent: threshold directo para escalate; Fidel já notificado encerra; resto → supervisor."""
    if state.get("stage") == "escalate":
        return "escalate"
    if state.get("fidel_notified"):
        return END
    return "supervisor"


def create_graph(checkpointer: BaseCheckpointSaver):
    """
    Constrói e compila o grafo LangGraph com Lusambu + Supervisor + Sales Agent.

    Fluxo:
      dispatcher → lusambu → supervisor (stages avançados) → END / escalate
      dispatcher → sales_agent (quando sales_agent_active=True) → END / escalate
    """
    builder = StateGraph(LusambuState)

    builder.add_node("dispatcher", lambda s: s)
    builder.add_node("lusambu", lusambu_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("sales_agent", sales_agent_node)
    builder.add_node("discard", discard_node)
    builder.add_node("escalate", escalate_node)

    builder.set_entry_point("dispatcher")

    builder.add_conditional_edges("dispatcher", _dispatcher_router, {
        "lusambu": "lusambu",
        "sales_agent": "sales_agent",
    })

    builder.add_conditional_edges("lusambu", _after_lusambu_router, {
        "discard": "discard",
        "escalate": "escalate",
        "supervisor": "supervisor",
        END: END,
    })

    builder.add_conditional_edges("supervisor", _after_supervisor_router, {
        "escalate": "escalate",
        END: END,
    })

    builder.add_conditional_edges("sales_agent", _after_sales_router, {
        "escalate": "escalate",
        "supervisor": "supervisor",
        END: END,
    })

    builder.add_edge("discard", END)
    builder.add_edge("escalate", END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Grafo Lusambu + Sales Agent compilado com sucesso.")
    return graph

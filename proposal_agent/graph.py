import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from .state import ProposalState
from .nodes import (
    load_context_node,
    generate_proposal_node,
    regenerate_proposal_node,
    send_to_fidel_node,
    wait_for_fidel_node,
    send_to_client_node,
    mark_approved_node,
    mark_rejected_node,
)

logger = logging.getLogger(__name__)


def _route_fidel_decision(state: ProposalState) -> str:
    decision = state.get("fidel_decision", "")
    if decision == "aprovar":
        return "send_to_client"
    if decision == "editar":
        return "regenerate_proposal"
    return "mark_rejected"


def create_proposal_graph(checkpointer: BaseCheckpointSaver):
    """
    Grafo de aprovação de propostas:
      load_context → generate_proposal → send_to_fidel → wait_for_fidel
        → aprovar  → send_to_client → mark_approved → END
        → editar   → regenerate_proposal → send_to_fidel (loop)
        → rejeitar → mark_rejected → END
    """
    builder = StateGraph(ProposalState)

    builder.add_node("load_context",        load_context_node)
    builder.add_node("generate_proposal",   generate_proposal_node)
    builder.add_node("send_to_fidel",       send_to_fidel_node)
    builder.add_node("wait_for_fidel",      wait_for_fidel_node)
    builder.add_node("regenerate_proposal", regenerate_proposal_node)
    builder.add_node("send_to_client",      send_to_client_node)
    builder.add_node("mark_approved",       mark_approved_node)
    builder.add_node("mark_rejected",       mark_rejected_node)

    builder.set_entry_point("load_context")
    builder.add_edge("load_context",        "generate_proposal")
    builder.add_edge("generate_proposal",   "send_to_fidel")
    builder.add_edge("send_to_fidel",       "wait_for_fidel")

    builder.add_conditional_edges("wait_for_fidel", _route_fidel_decision, {
        "send_to_client":      "send_to_client",
        "regenerate_proposal": "regenerate_proposal",
        "mark_rejected":       "mark_rejected",
    })

    builder.add_edge("send_to_client",      "mark_approved")
    builder.add_edge("mark_approved",       END)
    builder.add_edge("regenerate_proposal", "send_to_fidel")
    builder.add_edge("mark_rejected",       END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Grafo PROPOSAL compilado.")
    return graph

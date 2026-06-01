import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from .state import InvoiceState
from .nodes import (
    load_context_node,
    generate_preview_node,
    regenerate_preview_node,
    send_to_fidel_node,
    wait_for_fidel_node,
    finalize_invoice_node,
    notify_rejection_node,
)

logger = logging.getLogger(__name__)


def _route_fidel_decision(state: InvoiceState) -> str:
    decision = state.get("fidel_decision", "")
    if decision == "aprovar":
        return "finalize_invoice"
    if decision == "editar":
        return "regenerate_preview"
    return "notify_rejection"


def create_invoice_graph(checkpointer: BaseCheckpointSaver):
    """
    Grafo de emissão de facturas:
      load_context → generate_preview → send_to_fidel → wait_for_fidel
        → aprovar  → finalize_invoice → END
        → editar   → regenerate_preview → send_to_fidel (loop)
        → rejeitar → notify_rejection → END
    """
    builder = StateGraph(InvoiceState)

    builder.add_node("load_context",       load_context_node)
    builder.add_node("generate_preview",   generate_preview_node)
    builder.add_node("send_to_fidel",      send_to_fidel_node)
    builder.add_node("wait_for_fidel",     wait_for_fidel_node)
    builder.add_node("regenerate_preview", regenerate_preview_node)
    builder.add_node("finalize_invoice",   finalize_invoice_node)
    builder.add_node("notify_rejection",   notify_rejection_node)

    builder.set_entry_point("load_context")
    builder.add_edge("load_context",       "generate_preview")
    builder.add_edge("generate_preview",   "send_to_fidel")
    builder.add_edge("send_to_fidel",      "wait_for_fidel")

    builder.add_conditional_edges("wait_for_fidel", _route_fidel_decision, {
        "finalize_invoice":  "finalize_invoice",
        "regenerate_preview": "regenerate_preview",
        "notify_rejection":  "notify_rejection",
    })

    builder.add_edge("finalize_invoice",   END)
    builder.add_edge("regenerate_preview", "send_to_fidel")
    builder.add_edge("notify_rejection",   END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Grafo INVOICE compilado.")
    return graph

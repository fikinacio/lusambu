import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from .state import ProjectState
from .nodes import (
    load_context_node,
    generate_milestones_node,
    regenerate_milestones_node,
    send_to_fidel_node,
    wait_for_fidel_node,
    create_notion_page_node,
    save_project_node,
    send_welcome_node,
)

logger = logging.getLogger(__name__)


def _route_fidel_decision(state: ProjectState) -> str:
    decision = state.get("fidel_decision", "editar")
    if decision == "aprovar":
        return "create_notion_page"
    return "regenerate_milestones"


def create_project_graph(checkpointer: BaseCheckpointSaver):
    """
    Grafo de arranque de projectos:
      load_context → generate_milestones → send_to_fidel → wait_for_fidel
        → aprovar → create_notion_page → save_project → send_welcome → END
        → editar  → regenerate_milestones → send_to_fidel (loop)
    """
    builder = StateGraph(ProjectState)

    builder.add_node("load_context",          load_context_node)
    builder.add_node("generate_milestones",   generate_milestones_node)
    builder.add_node("send_to_fidel",         send_to_fidel_node)
    builder.add_node("wait_for_fidel",        wait_for_fidel_node)
    builder.add_node("regenerate_milestones", regenerate_milestones_node)
    builder.add_node("create_notion_page",    create_notion_page_node)
    builder.add_node("save_project",          save_project_node)
    builder.add_node("send_welcome",          send_welcome_node)

    builder.set_entry_point("load_context")
    builder.add_edge("load_context",        "generate_milestones")
    builder.add_edge("generate_milestones", "send_to_fidel")
    builder.add_edge("send_to_fidel",       "wait_for_fidel")

    builder.add_conditional_edges("wait_for_fidel", _route_fidel_decision, {
        "create_notion_page":    "create_notion_page",
        "regenerate_milestones": "regenerate_milestones",
    })

    builder.add_edge("regenerate_milestones", "send_to_fidel")
    builder.add_edge("create_notion_page",    "save_project")
    builder.add_edge("save_project",          "send_welcome")
    builder.add_edge("send_welcome",          END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Grafo PROJECT MANAGER compilado.")
    return graph

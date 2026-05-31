import pytest
from langgraph.checkpoint.memory import MemorySaver
from proposal_agent.graph import create_proposal_graph


def test_create_proposal_graph_compiles():
    """O grafo compila sem erros com MemorySaver."""
    graph = create_proposal_graph(MemorySaver())
    assert graph is not None


def test_proposal_graph_has_expected_nodes():
    graph = create_proposal_graph(MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "load_context", "generate_proposal", "send_to_fidel",
        "wait_for_fidel", "regenerate_proposal", "send_to_client",
        "mark_approved", "mark_rejected",
    }
    assert expected.issubset(node_names)

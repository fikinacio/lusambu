import pytest
from langgraph.checkpoint.memory import MemorySaver
from invoice_agent.graph import create_invoice_graph


def test_create_invoice_graph_compiles():
    """O grafo compila sem erros com MemorySaver."""
    graph = create_invoice_graph(MemorySaver())
    assert graph is not None


def test_invoice_graph_has_expected_nodes():
    graph = create_invoice_graph(MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "load_context", "generate_preview", "send_to_fidel",
        "wait_for_fidel", "regenerate_preview", "finalize_invoice",
        "notify_rejection",
    }
    assert expected.issubset(node_names)

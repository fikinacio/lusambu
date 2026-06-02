import pytest
from langgraph.checkpoint.memory import MemorySaver
from project_agent.graph import create_project_graph


def test_create_project_graph_compiles():
    '''O grafo compila sem erros com MemorySaver.'''
    graph = create_project_graph(MemorySaver())
    assert graph is not None


def test_project_graph_has_expected_nodes():
    graph = create_project_graph(MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        'load_context', 'generate_milestones', 'send_to_fidel',
        'wait_for_fidel', 'regenerate_milestones', 'create_notion_page',
        'save_project', 'send_welcome',
    }
    assert expected.issubset(node_names)

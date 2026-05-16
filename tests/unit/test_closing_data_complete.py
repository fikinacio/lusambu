"""
Testes unitários de _closing_data_complete — verifica se o lead já forneceu
todos os dados necessários para o sistema enviar o link Calendly.
"""
from agent.nodes import _closing_data_complete


def test_completo_com_nome_empresa_e_horario():
    lead = {"name": "Pedro", "company": "Contaplus", "scheduled_time": "segunda de manhã"}
    assert _closing_data_complete(lead) is True


def test_incompleto_sem_nome():
    lead = {"company": "Contaplus", "scheduled_time": "segunda"}
    assert _closing_data_complete(lead) is False


def test_incompleto_sem_empresa():
    lead = {"name": "Pedro", "scheduled_time": "segunda"}
    assert _closing_data_complete(lead) is False


def test_incompleto_sem_horario():
    lead = {"name": "Pedro", "company": "Contaplus"}
    assert _closing_data_complete(lead) is False


def test_incompleto_com_string_vazia():
    """Strings vazias contam como ausência (bool('') é False)."""
    lead = {"name": "", "company": "Contaplus", "scheduled_time": "segunda"}
    assert _closing_data_complete(lead) is False


def test_estado_vazio_e_incompleto():
    assert _closing_data_complete({}) is False


def test_incompleto_com_valores_none():
    lead = {"name": None, "company": "Contaplus", "scheduled_time": "segunda"}
    assert _closing_data_complete(lead) is False

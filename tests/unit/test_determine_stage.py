"""
Testes unitários de _determine_stage — função que decide o próximo stage do agente.
É pura (sem I/O), por isso cada caso é determinístico e rápido.
"""
import pytest
from agent.nodes import _determine_stage


# ---------------------------------------------------------------------------
# Descarte
# ---------------------------------------------------------------------------

def test_descarta_quando_sem_empresa():
    assert _determine_stage({"has_business": False}, 0) == "discard"


def test_descarta_mesmo_com_objeccao():
    """has_business=False tem precedência sobre tudo."""
    assert _determine_stage({"has_business": False, "is_objecting": True}, 1) == "discard"


# ---------------------------------------------------------------------------
# Escalação
# ---------------------------------------------------------------------------

def test_escala_quando_quer_humano():
    lead = {"has_business": True, "wants_human": True}
    assert _determine_stage(lead, 0) == "escalate"


def test_escala_quando_duas_objeccoes():
    lead = {"has_business": True, "wants_human": False, "is_objecting": True}
    assert _determine_stage(lead, 2) == "escalate"


def test_escala_quando_pronto_para_fechar():
    lead = {"has_business": True, "wants_human": False, "ready_to_close": True}
    assert _determine_stage(lead, 0) == "escalate"


def test_escala_com_wants_human_tem_prioridade_sobre_objeccao():
    """wants_human verifica-se antes de ready_to_close — ambos escalam, ordem não importa."""
    lead = {"has_business": True, "wants_human": True, "ready_to_close": True}
    assert _determine_stage(lead, 0) == "escalate"


# ---------------------------------------------------------------------------
# Objecção
# ---------------------------------------------------------------------------

def test_objection_stage():
    lead = {"has_business": True, "wants_human": False, "is_objecting": True}
    assert _determine_stage(lead, 0) == "objection"


def test_objection_com_uma_objeccao_ainda_nao_escala():
    lead = {"has_business": True, "wants_human": False, "is_objecting": True}
    assert _determine_stage(lead, 1) == "objection"


# ---------------------------------------------------------------------------
# Pitch
# ---------------------------------------------------------------------------

def test_pitch_quando_tem_sector_e_dor():
    lead = {
        "has_business": True,
        "sector": "Comércio",
        "pain_point": "Atendimento lento",
    }
    assert _determine_stage(lead, 0) == "pitch"


def test_nao_vai_para_pitch_sem_dor():
    lead = {"has_business": True, "sector": "Comércio"}
    assert _determine_stage(lead, 0) == "qualify"


def test_nao_vai_para_pitch_sem_sector():
    lead = {"has_business": True, "pain_point": "Atendimento lento"}
    assert _determine_stage(lead, 0) == "qualify"


# ---------------------------------------------------------------------------
# Qualificação (default)
# ---------------------------------------------------------------------------

def test_qualify_quando_empresa_ainda_desconhecida():
    """has_business=None significa que ainda não perguntámos — fica em qualify."""
    assert _determine_stage({"has_business": None}, 0) == "qualify"


def test_qualify_quando_tem_empresa_sem_mais_info():
    assert _determine_stage({"has_business": True}, 0) == "qualify"


def test_qualify_estado_vazio():
    assert _determine_stage({}, 0) == "qualify"

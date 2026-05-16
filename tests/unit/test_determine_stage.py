"""
Testes unitários de _determine_stage — função que decide o próximo stage do agente.
É pura (sem I/O), por isso cada caso é determinístico e rápido.
"""
import pytest
from agent.nodes import _determine_stage, MAX_TURNS


# ---------------------------------------------------------------------------
# Descarte
# ---------------------------------------------------------------------------

def test_descarta_quando_sem_empresa():
    assert _determine_stage({"has_business": False}, 0, 1) == "discard"


def test_descarta_mesmo_com_objeccao():
    """has_business=False tem precedência sobre tudo."""
    assert _determine_stage({"has_business": False, "is_objecting": True}, 1, 1) == "discard"


# ---------------------------------------------------------------------------
# Escalação
# ---------------------------------------------------------------------------

def test_escala_quando_quer_humano():
    lead = {"has_business": True, "wants_human": True}
    assert _determine_stage(lead, 0, 1) == "escalate"


def test_escala_quando_duas_objeccoes():
    lead = {"has_business": True, "wants_human": False, "is_objecting": True}
    assert _determine_stage(lead, 2, 3) == "escalate"


def test_escala_quando_fluxo_de_closing_termina():
    """ready_to_close + nome + empresa + confirmado + Calendly enviado => escala."""
    lead = {
        "has_business": True,
        "wants_human": False,
        "ready_to_close": True,
        "name": "Ana",
        "company": "ImobAO",
    }
    assert _determine_stage(lead, 0, 4, data_confirmed=True, calendly_sent=True) == "escalate"


def test_escala_por_turnos_excessivos():
    """Conversa que se arrasta acaba escalada para revisão humana."""
    lead = {"has_business": True}
    assert _determine_stage(lead, 0, MAX_TURNS) == "escalate"


def test_escala_com_wants_human_tem_prioridade_sobre_objeccao():
    """wants_human verifica-se antes de ready_to_close — ambos escalam, ordem não importa."""
    lead = {"has_business": True, "wants_human": True, "ready_to_close": True}
    assert _determine_stage(lead, 0, 1) == "escalate"


# ---------------------------------------------------------------------------
# Closing — recolha de dados antes de escalar
# ---------------------------------------------------------------------------

def test_closing_sub_etapa_1_falta_nome_e_empresa():
    """Aceitou a chamada mas ainda não disse nome nem empresa — pede ambos."""
    lead = {"has_business": True, "ready_to_close": True}
    assert _determine_stage(lead, 0, 4) == "closing"


def test_closing_sub_etapa_1_falta_so_empresa():
    """Tem nome mas falta empresa — ainda em closing (sub-etapa 1)."""
    lead = {"has_business": True, "ready_to_close": True, "name": "Pedro"}
    assert _determine_stage(lead, 0, 4) == "closing"


def test_closing_sub_etapa_2_dados_completos_sem_confirmacao():
    """Nome e empresa recolhidos mas lead ainda não confirmou o resumo."""
    lead = {"has_business": True, "ready_to_close": True, "name": "Pedro", "company": "Contaplus"}
    assert _determine_stage(lead, 0, 4, data_confirmed=False, calendly_sent=False) == "closing"


def test_closing_sub_etapa_3_confirmado_mas_calendly_nao_enviado():
    """Lead confirmou mas o link ainda não foi enviado — continua em closing."""
    lead = {"has_business": True, "ready_to_close": True, "name": "Pedro", "company": "Contaplus"}
    assert _determine_stage(lead, 0, 4, data_confirmed=True, calendly_sent=False) == "closing"


def test_wants_human_escala_mesmo_sem_dados():
    """Se o lead pede humano explicitamente, escala já — humano vai recolher os dados."""
    lead = {"has_business": True, "wants_human": True, "ready_to_close": False}
    assert _determine_stage(lead, 0, 4) == "escalate"


# ---------------------------------------------------------------------------
# Objecção
# ---------------------------------------------------------------------------

def test_objection_stage():
    lead = {"has_business": True, "wants_human": False, "is_objecting": True}
    assert _determine_stage(lead, 0, 2) == "objection"


def test_objection_com_uma_objeccao_ainda_nao_escala():
    lead = {"has_business": True, "wants_human": False, "is_objecting": True}
    assert _determine_stage(lead, 1, 2) == "objection"


# ---------------------------------------------------------------------------
# Pitch
# ---------------------------------------------------------------------------

def test_pitch_quando_tem_sector_e_dor():
    lead = {
        "has_business": True,
        "sector": "Comércio",
        "pain_point": "Atendimento lento",
    }
    assert _determine_stage(lead, 0, 2) == "pitch"


def test_nao_vai_para_pitch_sem_dor():
    lead = {"has_business": True, "sector": "Comércio"}
    assert _determine_stage(lead, 0, 2) == "qualify"


def test_nao_vai_para_pitch_sem_sector():
    lead = {"has_business": True, "pain_point": "Atendimento lento"}
    assert _determine_stage(lead, 0, 2) == "qualify"


# ---------------------------------------------------------------------------
# Qualificação (default)
# ---------------------------------------------------------------------------

def test_qualify_quando_empresa_ainda_desconhecida():
    """has_business=None significa que ainda não perguntámos — fica em qualify."""
    assert _determine_stage({"has_business": None}, 0, 1) == "qualify"


def test_qualify_quando_tem_empresa_sem_mais_info():
    assert _determine_stage({"has_business": True}, 0, 1) == "qualify"


def test_qualify_estado_vazio():
    assert _determine_stage({}, 0, 1) == "qualify"

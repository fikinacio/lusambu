"""
Testes unitários de load_outreach_context — resolução de lead_origin.
Garante que:
- um prospect com mensagem de prospecção enviada é sempre classificado como "outbound",
  mesmo que o webhook tenha (erradamente) marcado outra origem;
- na ausência de outbound, a origem detectada no primeiro contacto (site/facebook_ads)
  é preservada entre turnos;
- sem qualquer sinal, a origem cai para "unknown".
"""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage

from agent.nodes import load_outreach_context


def _base_state(**overrides) -> dict:
    state = {
        "messages": [HumanMessage(content="Olá")],
        "whatsapp_number": "244923000000",
        "lead_origin": "unknown",
        "ad_context": None,
    }
    state.update(overrides)
    return state


def _patch_supabase(outreach_msg=None, prospect=None, empresa=None):
    return (
        patch("agent.nodes.get_outreach_message", AsyncMock(return_value=outreach_msg)),
        patch("agent.nodes.get_mensagens_history", AsyncMock(return_value=[])),
        patch("agent.nodes.get_prospect_context", AsyncMock(return_value=prospect)),
        patch("agent.nodes._resolve_empresa", AsyncMock(return_value=empresa)),
        patch("agent.nodes.get_prospect_by_id", AsyncMock(return_value=None)),
        patch("agent.nodes.get_message_history", AsyncMock(return_value=[])),
    )


async def test_prospect_com_outreach_e_sempre_outbound():
    patches = _patch_supabase(outreach_msg="Olá, somos a BMST...", prospect={"empresa_nome": "Loja X"})
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        result = await load_outreach_context(_base_state(lead_origin="site"))

    assert result["outreach_source"] == "outbound"
    assert result["lead_origin"] == "outbound"


async def test_sem_outbound_preserva_origem_facebook_ads_entre_turnos():
    patches = _patch_supabase(outreach_msg=None, prospect=None)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        result = await load_outreach_context(_base_state(lead_origin="facebook_ads"))

    assert result["outreach_source"] == "inbound"
    assert result["lead_origin"] == "facebook_ads"


async def test_sem_outbound_preserva_origem_site_entre_turnos():
    patches = _patch_supabase(outreach_msg=None, prospect=None)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        result = await load_outreach_context(_base_state(lead_origin="site"))

    assert result["outreach_source"] == "inbound"
    assert result["lead_origin"] == "site"


async def test_sem_sinal_nenhum_cai_para_unknown():
    patches = _patch_supabase(outreach_msg=None, prospect=None)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        result = await load_outreach_context(_base_state(lead_origin=""))

    assert result["outreach_source"] == "inbound"
    assert result["lead_origin"] == "unknown"

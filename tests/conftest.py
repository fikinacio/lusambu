import os

# Define variáveis de ambiente antes de qualquer import do projecto.
# pydantic-settings lê os valores no momento da importação de config.py;
# sem isto todos os testes falhariam com ValidationError.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-supabase-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("EVOLUTION_API_URL", "https://test.evolution.com")
os.environ.setdefault("EVOLUTION_API_KEY", "test-evolution-key")
os.environ.setdefault("EVOLUTION_INSTANCE", "lusambu-test")
os.environ.setdefault("FIDEL_WHATSAPP_NUMBER", "244923000000")

import pytest
from langchain_core.messages import HumanMessage
from agent.state import LusambuState


@pytest.fixture
def estado_inicial() -> LusambuState:
    """Estado base para qualquer conversa nova."""
    return {
        "messages": [HumanMessage(content="Olá, vi o vosso anúncio")],
        "whatsapp_number": "244923111111",
        "lead_info": {},
        "stage": "qualify",
        "objection_count": 0,
        "escalation_reason": "",
        "fidel_notified": False,
    }

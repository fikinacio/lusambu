import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent.state import LusambuState
from .prompts import SUPERVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

llm_supervisor = ChatAnthropic(model="claude-sonnet-4-6", temperature=0, max_tokens=512)


def _format_history(messages: list) -> str:
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            role = "LEAD"
        elif isinstance(m, AIMessage):
            role = "BISCA+"
        else:
            role = "MSG"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


async def supervisor_node(state: LusambuState) -> LusambuState:
    """
    Avalia a conversa após cada turno do Lusambu.
    Decide se o Sales Agent deve entrar (passa_para_sales)
    ou se é necessário escalar para Fidel (escala_para_fidel).
    Corre apenas em stages pitch, objection ou closing.
    """
    messages = list(state.get("messages", []))
    historico = _format_history(messages)

    prompt = f"""Histórico da conversa:
{historico}

Avalia o estado actual e devolve o JSON de decisão."""

    try:
        response = await llm_supervisor.ainvoke([
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        decisao = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Supervisor: JSON inválido — {response.content[:200]}")
        decisao = {
            "estado": "continua_qualificacao",
            "razao": "erro ao processar JSON — manter qualificação",
            "dor_confirmada": None,
            "decisor_confirmado": False,
        }
    except Exception as e:
        logger.error(f"Supervisor: erro inesperado — {e}")
        decisao = {
            "estado": "continua_qualificacao",
            "razao": "erro inesperado — manter qualificação",
            "dor_confirmada": None,
            "decisor_confirmado": False,
        }

    estado = decisao.get("estado", "continua_qualificacao")
    logger.info(f"Supervisor: {estado} — {decisao.get('razao', '')}")

    # Uma vez activo, o Sales Agent mantém o controlo mesmo que o supervisor reavalie
    sales_active = estado == "passa_para_sales" or bool(state.get("sales_agent_active"))

    escalation_reason = state.get("escalation_reason", "")
    if estado == "escala_para_fidel":
        escalation_reason = decisao.get("razao", "Supervisão de vendas — escalada necessária")

    return {
        **state,
        "supervisor_decision": decisao,
        "sales_agent_active": sales_active,
        "escalation_reason": escalation_reason,
    }

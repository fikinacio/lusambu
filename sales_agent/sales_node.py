import asyncio
import logging
import random
import re

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent.state import LusambuState
from integrations.evolution import send_whatsapp_message, send_typing_indicator
from integrations.rag import consultar_conhecimento
from .prompts import SALES_AGENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

llm_sales = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=500, temperature=0.3)

# Padrões que exigem escalada para Fidel antes de responder
_ESCALATION_PATTERNS = [
    (re.compile(r"desconto\D{0,25}(\d+)\s*%", re.IGNORECASE), "pct_desconto"),
    (re.compile(r"300[.\s]?000|350[.\s]?000|400[.\s]?000", re.IGNORECASE), "valor_alto"),
    (re.compile(r"cl[aá]usula|negociar\s+termos|condi[cç][oõ]es\s+especiais", re.IGNORECASE), "contrato"),
]


async def _human_delay() -> None:
    await asyncio.sleep(random.uniform(3, 8))


def _check_escalation(message: str) -> tuple[bool, str]:
    """Retorna (deve_escalar, razao). Verifica thresholds de desconto e valor."""
    for pattern, tipo in _ESCALATION_PATTERNS:
        m = pattern.search(message)
        if m:
            if tipo == "pct_desconto":
                pct = int(m.group(1))
                if pct > 10:
                    return True, f"Pedido de desconto acima do threshold: {pct}%"
            else:
                label = "Setup acima de 300.000 AOA" if tipo == "valor_alto" else "Negociação de contrato/cláusulas"
                return True, label
    return False, ""


async def sales_agent_node(state: LusambuState) -> LusambuState:
    """
    Fecha negócios quando o lead está maduro.
    Substitui o Lusambu — o lead não nota a transição.
    Usa RAG para contexto sobre portfólio, preços e casos reais.
    Escala para Fidel via escalate_node quando o threshold é atingido.
    """
    # Conversa já encerrada ou Fidel já notificado — não responder
    if state.get("fidel_notified") or state.get("stage") in ("end", "discard"):
        return state

    messages = list(state.get("messages", []))
    last_human = next(
        (m.content for m in reversed(messages) if isinstance(m, HumanMessage)),
        "",
    )

    # Verificar se é necessário escalar para Fidel antes de responder
    should_escalate, esc_reason = _check_escalation(last_human)
    if should_escalate:
        holding = "Deixa-me confirmar um detalhe e respondo-te em breve."
        await send_typing_indicator(state["whatsapp_number"])
        await _human_delay()
        await send_whatsapp_message(state["whatsapp_number"], holding)
        logger.info(f"Sales Agent: escalada para Fidel — {esc_reason}")
        return {
            **state,
            "messages": [AIMessage(content=holding)],
            "stage": "escalate",
            "escalation_reason": esc_reason,
        }

    # Contexto RAG relevante para a dor do lead
    dor = state.get("supervisor_decision", {}).get("dor_confirmada", "")
    rag_query = f"solução para: {dor}" if dor else "portfólio bisca+ preços casos"
    rag_context = await consultar_conhecimento(rag_query) or ""

    # Histórico formatado para o LLM
    historico = "\n".join([
        f"{'LEAD' if isinstance(m, HumanMessage) else 'BISCA+'}: {m.content}"
        for m in messages
    ])

    prompt = f"""CONTEXTO DA EMPRESA (RAG):
{rag_context if rag_context else "(Sem informação verificada na base de conhecimento para esta pergunta. NÃO inventes preços, prazos, integrações ou resultados. Se não conseguires responder com segurança, diz que vais confirmar com a equipa e avança para agendar uma chamada.)"}

HISTÓRICO DA CONVERSA:
{historico}

Dor confirmada: {dor or "(não especificada — infere pelo histórico)"}

Responde como Sales Agent. Uma mensagem, directa, orientada a fechar."""

    response = await llm_sales.ainvoke([
        SystemMessage(content=SALES_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])

    await send_typing_indicator(state["whatsapp_number"])
    await _human_delay()
    await send_whatsapp_message(state["whatsapp_number"], response.content)

    return {
        **state,
        "messages": [AIMessage(content=response.content)],
    }

import json
import logging
import os
from datetime import date, timedelta

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.types import interrupt

from .state import ProjectState
from .prompts import PROJECT_MILESTONES_PROMPT, PROJECT_EDIT_PROMPT, WELCOME_MESSAGE, APPROVAL_BUTTONS_2
from integrations.evolution import send_whatsapp_message, send_button_message
from integrations.notion import add_communication_log, create_project_page
from integrations.supabase_client import (
    get_deal_for_project,
    get_company_config,
    save_project,
    update_project,
    save_project_milestones,
)

logger = logging.getLogger(__name__)

llm_project = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=600, temperature=0.3)

FIDEL_NUMBER = os.getenv("FIDEL_WHATSAPP", "")

_MILESTONE_TEMPLATES = {
    "Chatbots & Assistentes IA": [
        {"nome": "Kickoff e levantamento de requisitos", "ordem": 1, "dias_fim": 3},
        {"nome": "Aprovação do fluxo conversacional", "ordem": 2, "dias_fim": 7},
        {"nome": "Desenvolvimento e integração", "ordem": 3, "dias_fim": 18},
        {"nome": "Testes e ajustes", "ordem": 4, "dias_fim": 23},
        {"nome": "Entrega e formação", "ordem": 5, "dias_fim": 30},
    ],
    "Automação de Processos": [
        {"nome": "Kickoff e mapeamento do processo actual", "ordem": 1, "dias_fim": 3},
        {"nome": "Aprovação da arquitectura de automação", "ordem": 2, "dias_fim": 7},
        {"nome": "Desenvolvimento dos workflows", "ordem": 3, "dias_fim": 20},
        {"nome": "Testes em ambiente real", "ordem": 4, "dias_fim": 25},
        {"nome": "Entrega e documentação", "ordem": 5, "dias_fim": 30},
    ],
    "Agentes de IA Autónomos": [
        {"nome": "Kickoff e definição de objectivos do agente", "ordem": 1, "dias_fim": 4},
        {"nome": "Aprovação da arquitectura e ferramentas", "ordem": 2, "dias_fim": 9},
        {"nome": "Desenvolvimento do agente", "ordem": 3, "dias_fim": 25},
        {"nome": "Testes e validação", "ordem": 4, "dias_fim": 32},
        {"nome": "Deploy e monitorização inicial", "ordem": 5, "dias_fim": 40},
    ],
    "Equipas de Agentes Orquestradas": [
        {"nome": "Kickoff e arquitectura multi-agente", "ordem": 1, "dias_fim": 5},
        {"nome": "Aprovação do design do sistema", "ordem": 2, "dias_fim": 10},
        {"nome": "Desenvolvimento dos agentes individuais", "ordem": 3, "dias_fim": 30},
        {"nome": "Integração e testes de orquestração", "ordem": 4, "dias_fim": 40},
        {"nome": "Deploy e documentação completa", "ordem": 5, "dias_fim": 50},
    ],
    "Dados & Business Intelligence": [
        {"nome": "Kickoff e auditoria de dados existentes", "ordem": 1, "dias_fim": 4},
        {"nome": "Aprovação da arquitectura de dados", "ordem": 2, "dias_fim": 8},
        {"nome": "Implementação da infra-estrutura", "ordem": 3, "dias_fim": 20},
        {"nome": "Desenvolvimento de dashboards e relatórios", "ordem": 4, "dias_fim": 30},
        {"nome": "Entrega e formação", "ordem": 5, "dias_fim": 35},
    ],
    "Infraestrutura & Cibersegurança": [
        {"nome": "Kickoff e auditoria de segurança", "ordem": 1, "dias_fim": 5},
        {"nome": "Relatório de vulnerabilidades e plano", "ordem": 2, "dias_fim": 10},
        {"nome": "Implementação de controlos", "ordem": 3, "dias_fim": 25},
        {"nome": "Testes de penetração e validação", "ordem": 4, "dias_fim": 32},
        {"nome": "Entrega e documentação", "ordem": 5, "dias_fim": 40},
    ],
    "Formação & Consultoria": [
        {"nome": "Kickoff e diagnóstico de necessidades", "ordem": 1, "dias_fim": 3},
        {"nome": "Aprovação do plano formativo", "ordem": 2, "dias_fim": 6},
        {"nome": "Desenvolvimento de materiais", "ordem": 3, "dias_fim": 14},
        {"nome": "Sessões de formação", "ordem": 4, "dias_fim": 25},
        {"nome": "Avaliação e relatório final", "ordem": 5, "dias_fim": 30},
    ],
    "Retainer": [
        {"nome": "Kickoff e definição de SLAs", "ordem": 1, "dias_fim": 3},
        {"nome": "Aprovação do plano mensal", "ordem": 2, "dias_fim": 5},
        {"nome": "Revisão mensal de resultados", "ordem": 3, "dias_fim": 35},
        {"nome": "Relatório trimestral", "ordem": 4, "dias_fim": 90},
    ],
}

_DEFAULT_KEY = "Chatbots & Assistentes IA"


def _milestone_template(servico_tipo: str) -> list[dict]:
    """Devolve template de milestones para o tipo de serviço dado."""
    t = (servico_tipo or "").lower()
    if "chatbot" in t or "assistente" in t:
        key = "Chatbots & Assistentes IA"
    elif "equipa" in t and "agente" in t:
        key = "Equipas de Agentes Orquestradas"
    elif "agente" in t:
        key = "Agentes de IA Autónomos"
    elif "automação" in t or "automacao" in t or "automac" in t:
        key = "Automação de Processos"
    elif "dado" in t or "business" in t or "intelligence" in t:
        key = "Dados & Business Intelligence"
    elif "infra" in t or "ciber" in t or "segurança" in t or "seguranca" in t:
        key = "Infraestrutura & Cibersegurança"
    elif "forma" in t or "consul" in t:
        key = "Formação & Consultoria"
    elif "retainer" in t or "parceiro" in t:
        key = "Retainer"
    else:
        key = _DEFAULT_KEY
    return _MILESTONE_TEMPLATES.get(key, _MILESTONE_TEMPLATES[_DEFAULT_KEY])


def _parse_decision(text: str) -> str:
    """Normaliza resposta do Fidel para 'aprovar' | 'editar'."""
    t = (text or "").strip().lower()
    if t in ("1", "aprovar", "✅ aprovar", "✅aprovar", "approve"):
        return "aprovar"
    if t in ("2", "editar", "✏️ editar", "✏️editar", "edit", "corrigir"):
        return "editar"
    if "aprov" in t:
        return "aprovar"
    if "edit" in t or "corri" in t or "muda" in t or "altera" in t:
        return "editar"
    return "editar"


# ---------------------------------------------------------------------------
# Nós
# ---------------------------------------------------------------------------

async def load_context_node(state: ProjectState) -> ProjectState:
    """Lê dados do deal e configuração da empresa."""
    deal = await get_deal_for_project(state["whatsapp"])
    cfg = await get_company_config()
    if not deal:
        logger.warning(f"Deal não encontrado para projecto: {state['whatsapp']}")
        raise ValueError(f"Deal não encontrado para projecto: {state['whatsapp']}")
    return {
        **state,
        "empresa": deal.get("empresa") or "",
        "servico_tipo": deal.get("sector") or "",
        "valor": deal.get("valor") or 0.0,
        "contact_name": deal.get("contact_name") or "",
        "email": deal.get("email") or "",
        "canal_preferido": "whatsapp",
        "company_config": cfg,
    }


async def generate_milestones_node(state: ProjectState) -> ProjectState:
    """Gera milestones com base no tipo de serviço e formata via LLM."""
    servico_tipo = state.get("servico_tipo", "")
    template = _milestone_template(servico_tipo)
    today = date.today()
    milestones = [
        {
            "nome": m["nome"],
            "ordem": m["ordem"],
            "data_prevista": (today + timedelta(days=m["dias_fim"])).isoformat(),
        }
        for m in template
    ]

    cfg = state.get("company_config", {})
    prompt = PROJECT_MILESTONES_PROMPT.format(
        company_name=cfg.get("company_name", "BMST"),
        empresa=state.get("empresa", ""),
        servico_tipo=servico_tipo,
        milestones_json=json.dumps(milestones, ensure_ascii=False),
        data_inicio=today.isoformat(),
    )
    response = await llm_project.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content="Formata os milestones acima em preview para WhatsApp."),
    ])
    return {**state, "milestones": milestones, "milestones_preview": response.content.strip()}


async def regenerate_milestones_node(state: ProjectState) -> ProjectState:
    """Regenera preview de milestones incorporando correcções do Fidel."""
    prompt = PROJECT_EDIT_PROMPT.format(
        milestones_preview=state.get("milestones_preview", ""),
        edit_notes=state.get("edit_notes", ""),
    )
    response = await llm_project.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content="Ajusta o preview com as correcções indicadas."),
    ])
    iteration = state.get("iteration", 0) + 1
    return {**state, "milestones_preview": response.content.strip(), "iteration": iteration}


async def send_to_fidel_node(state: ProjectState) -> ProjectState:
    """Guarda projecto no Supabase e envia milestones + botões ao Fidel."""
    project_id = state.get("project_id")
    preview = state.get("milestones_preview", "")

    if not project_id:
        project_id = await save_project({
            "whatsapp": state["whatsapp"],
            "empresa": state.get("empresa", ""),
            "servico_tipo": state.get("servico_tipo", ""),
            "valor": state.get("valor"),
            "contact_name": state.get("contact_name", ""),
            "email": state.get("email", ""),
            "canal_preferido": state.get("canal_preferido", "whatsapp"),
            "milestones_preview": preview,
            "status": "draft",
            "iteration": state.get("iteration", 0),
        })
    else:
        await update_project(project_id, {
            "milestones_preview": preview,
            "edit_notes": None,
            "iteration": state.get("iteration", 0),
        })

    empresa = state.get("empresa", "cliente")
    header = f"📋 *Plano de Projecto para {empresa}*\n\n"
    await send_whatsapp_message(FIDEL_NUMBER, header + preview)

    iteration = state.get("iteration", 0)
    footer = f"Iteração {iteration + 1}" if iteration > 0 else "Fidel Kussunga | BMST"
    await send_button_message(
        number=FIDEL_NUMBER,
        body_text="Revê o plano de milestones. Qual é a tua decisão?",
        buttons=APPROVAL_BUTTONS_2,
        footer=footer,
    )

    return {**state, "project_id": project_id or ""}


async def wait_for_fidel_node(state: ProjectState) -> ProjectState:
    """Pausa o grafo e aguarda resposta do Fidel via interrupt."""
    fidel_message: str = interrupt("Aguarda decisão do Fidel (aprovar / editar)")
    decision = _parse_decision(fidel_message)
    return {
        **state,
        "fidel_decision": decision,
        "edit_notes": fidel_message if decision == "editar" else "",
    }


async def create_notion_page_node(state: ProjectState) -> ProjectState:
    """Cria página do projecto no Notion."""
    milestones = state.get("milestones", [])
    prazo = milestones[-1]["data_prevista"] if milestones else ""
    project_data = {
        "empresa": state.get("empresa"),
        "servico_tipo": state.get("servico_tipo"),
        "contact_name": state.get("contact_name"),
        "canal_preferido": state.get("canal_preferido", "whatsapp"),
        "email": state.get("email"),
        "valor": state.get("valor"),
        "data_inicio": date.today().isoformat(),
        "prazo_estimado": prazo,
        "milestones": milestones,
    }
    page_id = await create_project_page(project_data)
    return {**state, "notion_page_id": page_id}


async def save_project_node(state: ProjectState) -> ProjectState:
    """Actualiza projecto para em_curso e guarda milestones no Supabase."""
    milestones = state.get("milestones", [])
    prazo = milestones[-1]["data_prevista"] if milestones else None
    await update_project(state["project_id"], {
        "status": "em_curso",
        "notion_page_id": state.get("notion_page_id"),
        "prazo_estimado": prazo,
        "data_inicio": date.today().isoformat(),
    })
    milestones_for_db = [
        {"nome": m["nome"], "ordem": m["ordem"], "data_prevista": m["data_prevista"]}
        for m in milestones
    ]
    await save_project_milestones(state["project_id"], milestones_for_db)
    return state


async def send_welcome_node(state: ProjectState) -> ProjectState:
    """Envia mensagem de boas-vindas ao cliente."""
    nome = state.get("contact_name") or state.get("empresa", "")
    msg = WELCOME_MESSAGE.format(nome=nome)
    await send_whatsapp_message(state["whatsapp"], msg)
    if state.get("notion_page_id"):
        await add_communication_log(state["notion_page_id"], f"Boas-vindas enviadas ao cliente.")
    return state

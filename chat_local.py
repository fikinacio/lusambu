"""
chat_local.py — Conversa com a Lusambu directamente no terminal.

Não precisas de Redis, WhatsApp nem Supabase reais.
Apenas o ANTHROPIC_API_KEY no ficheiro .env.

Uso:
    python chat_local.py
"""
import asyncio
import os
import sys

# Força UTF-8 no stdout/stderr para suportar caracteres Unicode no Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 1. Carrega .env (sem dependência de python-dotenv)
# ---------------------------------------------------------------------------

def _load_dotenv(path: str = ".env") -> None:
    # Força leitura do .env — tem prioridade sobre o ambiente do processo pai.
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass


_load_dotenv()

# Valores dummy para campos obrigatórios pelo pydantic-settings (não usados em modo local)
os.environ.setdefault("SUPABASE_URL", "https://local.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "local-key")
os.environ.setdefault("CHECKPOINT_DB_PATH", "./local_checkpoints.sqlite")
os.environ.setdefault("EVOLUTION_API_URL", "https://local.evolution.com")
os.environ.setdefault("EVOLUTION_API_KEY", "local-key")
os.environ.setdefault("EVOLUTION_INSTANCE", "local")
os.environ.setdefault("FIDEL_WHATSAPP_NUMBER", "244900000000")


# ---------------------------------------------------------------------------
# 2. Imports do projecto (depois de definir env vars)
# ---------------------------------------------------------------------------

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage
from langchain_anthropic import ChatAnthropic  # noqa: F401  (usado em _llm_no_ssl)
import httpx
import anthropic as _anthropic

import integrations.evolution as evo
import integrations.supabase_client as sb
import agent.nodes as _nodes
import sales_agent.sales_node as _sales_node
import sales_agent.supervisor as _supervisor


def _llm_no_ssl(model: str, max_tokens: int, temperature: float) -> ChatAnthropic:
    """Cria um ChatAnthropic com verificação SSL desactivada (ambientes corporativos)."""
    llm = ChatAnthropic(model=model, max_tokens=max_tokens, temperature=temperature)
    # Substitui o cached_property _async_client por um sem SSL
    llm.__dict__["_async_client"] = _anthropic.AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        http_client=httpx.AsyncClient(verify=False),
    )
    return llm


_nodes.llm = _llm_no_ssl("claude-sonnet-4-6", 500, 0.7)
_nodes.llm_extractor = _llm_no_ssl("claude-sonnet-4-6", 300, 0.0)
_sales_node.llm_sales = _llm_no_ssl("claude-sonnet-4-6", 500, 0.3)
_supervisor.llm_supervisor = _llm_no_ssl("claude-sonnet-4-6", 512, 0.0)


# ---------------------------------------------------------------------------
# 3. Substituições de I/O — imprimem no terminal em vez de chamar APIs reais
# ---------------------------------------------------------------------------

async def _print_message(number: str, text: str) -> bool:
    print(f"\n\033[96mLusambu →\033[0m {text}\n")
    return True


async def _print_sales_message(number: str, text: str) -> bool:
    print(f"\n\033[92mSales Agent →\033[0m {text}\n")
    return True


async def _no_op(*args, **kwargs) -> None:
    pass


async def _print_lead(data: dict) -> bool:
    stage = data.get("stage", "—")
    cls = data.get("classification", "—")
    sector = data.get("sector") or "—"
    pain = data.get("pain_point") or "—"
    has_biz = data.get("has_business")
    print(f"  \033[90m[lead] stage={stage} | class={cls} | sector={sector} | dor={pain} | empresa={has_biz}\033[0m")
    return True


async def _print_fidel(message: str) -> bool:
    border = "━" * 44
    print(f"\n\033[93m{border}\n📲  ESCALAÇÃO → FIDEL\n{border}\033[0m")
    print(message)
    print(f"\033[93m{border}\033[0m\n")
    return True


async def _no_delay() -> None:
    """Remove o delay de 3–8 s para tornar o teste local instantâneo."""
    pass


# ---------------------------------------------------------------------------
# 4. Loop de conversa
# ---------------------------------------------------------------------------

async def main() -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-..."):
        print("\n\033[91mERRO: ANTHROPIC_API_KEY não encontrada.\033[0m")
        print("   Cria o ficheiro .env com:\n   ANTHROPIC_API_KEY=sk-ant-...\n")
        return

    # Grafo com checkpointer em memória (sem Redis)
    from agent.graph import create_graph
    graph = create_graph(MemorySaver())

    # Substitui no namespace de agent.nodes e sales_agent
    # (as funções já foram importadas por referência — substituir no módulo de origem não chegaria)
    _nodes.send_whatsapp_message = _print_message
    _nodes.notify_fidel = _print_fidel
    _nodes.upsert_lead = _print_lead
    _nodes._human_delay = _no_delay
    _sales_node.send_whatsapp_message = _print_sales_message
    _sales_node.send_typing_indicator = _no_op
    _sales_node._human_delay = _no_delay

    number = os.getenv("TEST_WHATSAPP_NUMBER", "244923000000")
    config = {"configurable": {"thread_id": number}}

    border = "━" * 44
    print(f"\n\033[95m{border}")
    print("  Lusambu — Modo Local")
    print(f"  Ctrl+C para sair\n{border}\033[0m\n")

    while True:
        try:
            user_input = input("\033[97mTu:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n[sessão encerrada]")
            break

        if not user_input:
            continue

        existing = await graph.aget_state(config)
        existing_stage = existing.values.get("stage") if existing.values else None

        if existing_stage == "end":
            offset = len(existing.values.get("messages", []))
            print(f"\033[90m[nova conversa iniciada — offset={offset}]\033[0m")
            state_input = {
                "messages": [HumanMessage(content=user_input)],
                "whatsapp_number": number,
                "lead_info": {},
                "stage": "qualify",
                "objection_count": 0,
                "turn_count": 0,
                "message_offset": offset,
                "prompt_variant": "",
                "escalation_reason": "",
                "fidel_notified": False,
                "data_confirmed": False,
                "calendly_sent": False,
                "supervisor_decision": {},
                "sales_agent_active": False,
            }
        elif existing.values:
            state_input = {"messages": [HumanMessage(content=user_input)]}
        else:
            state_input = {
                "messages": [HumanMessage(content=user_input)],
                "whatsapp_number": number,
                "lead_info": {},
                "stage": "qualify",
                "objection_count": 0,
                "turn_count": 0,
                "message_offset": 0,
                "prompt_variant": "",
                "escalation_reason": "",
                "fidel_notified": False,
                "data_confirmed": False,
                "calendly_sent": False,
                "supervisor_decision": {},
                "sales_agent_active": False,
            }

        try:
            result = await graph.ainvoke(state_input, config=config)
        except Exception as e:
            print(f"\n\033[91m[erro] {e}\033[0m\n")
            continue

        # Debug: estado do pipeline após cada turno
        stage = result.get("stage", "?")
        sales_active = result.get("sales_agent_active", False)
        sup = result.get("supervisor_decision", {})
        sup_estado = sup.get("estado", "") if sup else ""
        agent_label = "\033[92mSales Agent\033[0m" if sales_active else "\033[96mLusambu\033[0m"
        sup_info = f" | supervisor={sup_estado}" if sup_estado else ""
        print(f"  \033[90m[pipeline] agente={agent_label}\033[90m | stage={stage}{sup_info}\033[0m")

        if result.get("stage") == "end":
            print("\033[90m[conversa encerrada pelo agente]\033[0m")
            break


if __name__ == "__main__":
    asyncio.run(main())

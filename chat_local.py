"""
chat_local.py — Conversa com a Lusambu directamente no terminal.

Não precisas de Redis, WhatsApp nem Supabase reais.
Apenas o ANTHROPIC_API_KEY no ficheiro .env.

Uso:
    python chat_local.py
"""
import asyncio
import os


# ---------------------------------------------------------------------------
# 1. Carrega .env (sem dependência de python-dotenv)
# ---------------------------------------------------------------------------

def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()

# Valores dummy para campos obrigatórios pelo pydantic-settings (não usados em modo local)
os.environ.setdefault("SUPABASE_URL", "https://local.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "local-key")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:local@localhost:5432/postgres")
os.environ.setdefault("EVOLUTION_API_URL", "https://local.evolution.com")
os.environ.setdefault("EVOLUTION_API_KEY", "local-key")
os.environ.setdefault("EVOLUTION_INSTANCE", "local")
os.environ.setdefault("FIDEL_WHATSAPP_NUMBER", "244900000000")


# ---------------------------------------------------------------------------
# 2. Imports do projecto (depois de definir env vars)
# ---------------------------------------------------------------------------

from unittest.mock import patch
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

import integrations.evolution as evo
import integrations.supabase_client as sb
import agent.nodes as _nodes


# ---------------------------------------------------------------------------
# 3. Substituições de I/O — imprimem no terminal em vez de chamar APIs reais
# ---------------------------------------------------------------------------

async def _print_message(number: str, text: str) -> bool:
    print(f"\n\033[96mLusambu →\033[0m {text}\n")
    return True


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
        print("\n\033[91m❌  ANTHROPIC_API_KEY não encontrada.\033[0m")
        print("   Cria o ficheiro .env com:\n   ANTHROPIC_API_KEY=sk-ant-...\n")
        return

    # Grafo com checkpointer em memória (sem Redis)
    with patch("agent.graph.AsyncRedisSaver") as mock_redis:
        mock_redis.from_conn_string.return_value = MemorySaver()
        from agent.graph import create_graph
        graph = create_graph("redis://fake")

    # Substitui no namespace de agent.nodes — é lá que as funções foram importadas
    # (substituir nos módulos evo/sb não chegaria porque nodes.py já copiou as referências)
    _nodes.send_whatsapp_message = _print_message
    _nodes.notify_fidel = _print_fidel
    _nodes.upsert_lead = _print_lead
    _nodes._human_delay = _no_delay

    number = "local_244900000000"
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

        if existing.values:
            state_input = {"messages": [HumanMessage(content=user_input)]}
        else:
            state_input = {
                "messages": [HumanMessage(content=user_input)],
                "whatsapp_number": number,
                "lead_info": {},
                "stage": "qualify",
                "objection_count": 0,
                "escalation_reason": "",
                "fidel_notified": False,
            }

        try:
            result = await graph.ainvoke(state_input, config=config)
        except Exception as e:
            print(f"\n\033[91m[erro] {e}\033[0m\n")
            continue

        if result.get("stage") == "end":
            print("\033[90m[conversa encerrada pelo agente]\033[0m")
            break


if __name__ == "__main__":
    asyncio.run(main())

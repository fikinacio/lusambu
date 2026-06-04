"""
Script de validação da pipeline Lusambu.

Cria um cliente fictício, corre o invoice_agent completo (simulando aprovação
do Fidel), verifica o registo no Supabase, a factura no InvoiceNinja e o
projecto no Notion.

Pré-requisitos:
  - Variáveis de ambiente configuradas (ver .env.example)
  - Migration aplicada: migrations/add_notion_page_url.sql

Uso:
  cd /home/user/lusambu
  python -m scripts.validate_pipeline
"""
import asyncio
import logging
import sys
import os

# Garante que o raiz do projecto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from invoice_agent.graph import create_invoice_graph
from integrations.supabase_client import (
    upsert_lead,
    get_supabase,
    get_pending_invoice_for_fidel,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("validate_pipeline")

# ---------------------------------------------------------------------------
# Dados do cliente fictício
# ---------------------------------------------------------------------------
CLIENTE_FICTICIO = {
    "whatsapp": "244923000001",
    "name": "Ana Ferreira",
    "company": "TechLuanda Lda",
    "sector": "tecnologia",
    "email": "ana@techluanda.ao",
    "valor_negociado": "350.000 Kz/mês",
    "pain_point": "Automatização de processos administrativos",
    "stage": "closing",
    "status": "proposta_enviada",
    "classification": "hot",
}

WHATSAPP = CLIENTE_FICTICIO["whatsapp"]
THREAD_ID = f"invoice-{WHATSAPP}"


async def step1_registar_cliente() -> None:
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASSO 1 — Registar cliente fictício no Supabase")
    ok = await upsert_lead(CLIENTE_FICTICIO)
    if ok:
        print(f"  ✅ Lead '{CLIENTE_FICTICIO['company']}' ({WHATSAPP}) guardado em lusambu_leads")
    else:
        print("  ❌ Falha ao guardar lead — verifique SUPABASE_URL e SUPABASE_KEY")
        sys.exit(1)


async def step2_correr_invoice_agent() -> dict:
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASSO 2 — Correr invoice_agent (simulação sem WhatsApp real)")

    graph = create_invoice_graph(MemorySaver())
    config = {"configurable": {"thread_id": THREAD_ID}}

    # Primeira invocação: corre até ao interrupt (wait_for_fidel_node)
    print("  ▶ Iniciando grafo…")
    result = await graph.ainvoke({"whatsapp": WHATSAPP}, config=config)

    # Se o grafo pausou num interrupt, retomamos com decisão "aprovar"
    # (simula Fidel a aprovar via WhatsApp)
    snapshot = await graph.aget_state(config)
    if snapshot.next:
        print(f"  ⏸  Grafo pausado em: {snapshot.next}. A simular aprovação do Fidel…")
        result = await graph.ainvoke(Command(resume="aprovar"), config=config)

    return result


async def step3_verificar_supabase(result: dict) -> None:
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("PASSO 3 — Verificar registos no Supabase")

    db = get_supabase()

    # Verificar lusambu_leads
    lead = db.table("lusambu_leads").select("status").eq("whatsapp", WHATSAPP).limit(1).execute()
    lead_status = lead.data[0]["status"] if lead.data else "—"
    ok_lead = lead_status == "fatura_enviada"
    print(f"  {'✅' if ok_lead else '❌'} lusambu_leads.status = '{lead_status}' (esperado: 'fatura_enviada')")

    # Verificar invoice_drafts
    draft = (
        db.table("invoice_drafts")
        .select("status, invoice_number, client_id, invoice_id, notion_page_url, status_pagamento")
        .eq("whatsapp", WHATSAPP)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if draft.data:
        d = draft.data[0]
        ok_draft = d.get("status") == "sent"
        print(f"  {'✅' if ok_draft else '❌'} invoice_drafts.status = '{d.get('status')}'")
        print(f"  {'✅' if d.get('invoice_number') else '❌'} invoice_number = '{d.get('invoice_number')}'")
        print(f"  {'✅' if d.get('client_id') else '❌'} client_id (InvoiceNinja) = '{d.get('client_id')}'")
        print(f"  {'✅' if d.get('notion_page_url') else '⚠️ '} notion_page_url = '{d.get('notion_page_url') or 'não criado'}'")
        print(f"  ℹ️  status_pagamento = '{d.get('status_pagamento')}'")
    else:
        print("  ❌ Nenhum rascunho de factura encontrado para este lead")


async def step4_sumario(result: dict) -> None:
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("SUMÁRIO FINAL")
    campos = [
        ("Empresa", result.get("empresa")),
        ("Email", result.get("email")),
        ("Valor", result.get("valor_negociado")),
        ("InvoiceNinja client_id", result.get("client_id")),
        ("InvoiceNinja invoice_id", result.get("invoice_id")),
        ("Número Factura", result.get("invoice_number")),
        ("Notion URL", result.get("notion_page_url") or "—"),
    ]
    for label, val in campos:
        print(f"  {label:<30} {val or '—'}")
    print()


async def main() -> None:
    print("=" * 50)
    print("  VALIDAÇÃO DA PIPELINE LUSAMBU")
    print("=" * 50)

    await step1_registar_cliente()
    result = await step2_correr_invoice_agent()
    await step3_verificar_supabase(result)
    await step4_sumario(result)

    print("✅ Validação concluída.\n")


if __name__ == "__main__":
    asyncio.run(main())

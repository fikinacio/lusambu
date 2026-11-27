"""
rag_fase2b.py - Fase 2B: actualiza a base de conhecimento (tabela `documents`).

O que faz:
  1. Insere os 5 documentos das áreas de solução e os documentos de preços (de ingest.py).
  2. Actualiza o caso 42 (Jurídico) sem o nome do cliente e regenera o embedding.
  3. Apaga os 9 documentos dos serviços antigos (ids 33 a 41).
Os outros casos (43 a 48) não são tocados.

Por defeito só simula e mostra o que faria. Para executar: python rag_fase2b.py --apply
Usa o mesmo modelo de embeddings da base (text-embedding-3-small, 1536 dimensões).
Requer no .env: OPENAI_API_KEY, SUPABASE_URL, SUPABASE_KEY.
"""
import argparse
import os
import sys
import time

from ingest import CHUNKS, _load_dotenv

EMBEDDING_MODEL = "text-embedding-3-small"
OLD_SERVICE_IDS = list(range(33, 42))
OLD_SERVICE_NAMES = {
    "Automação de Processos",
    "Automação com IA",
    "Chatbots & Assistentes IA",
    "Agentes de IA Autónomos",
    "Equipas de Agentes Orquestradas",
    "Dados & Business Intelligence",
    "Infraestrutura & Cibersegurança",
    "Formação & Consultoria",
    "Retainer (Parceiro Contínuo)",
}
CASE_JURIDICO_ID = 42


def _new_documents() -> list[dict]:
    return [c for c in CHUNKS if c["metadata"].get("tipo") in ("servico", "preco", "preco_tabela")]


def _case_juridico() -> dict:
    matches = [c for c in CHUNKS if c["metadata"].get("tipo") == "caso" and c["metadata"].get("sector") == "Jurídico"]
    if len(matches) != 1:
        sys.exit("ERRO: caso Jurídico não encontrado (ou duplicado) em ingest.py")
    return matches[0]


def main(apply: bool) -> None:
    from openai import OpenAI
    from supabase import create_client

    _load_dotenv()
    for var in ("OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        if not os.getenv(var):
            sys.exit(f"ERRO: {var} não encontrada no .env")

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    # ---- Verificações antes de alterar seja o que for ----
    rows = db.table("documents").select("id, metadata").in_("id", OLD_SERVICE_IDS + [CASE_JURIDICO_ID]).execute().data
    by_id = {r["id"]: r["metadata"] or {} for r in rows}

    for doc_id in OLD_SERVICE_IDS:
        meta = by_id.get(doc_id)
        if meta is None:
            sys.exit(f"ERRO: documento {doc_id} não existe. Nada foi alterado.")
        if meta.get("tipo") != "servico" or meta.get("nome") not in OLD_SERVICE_NAMES:
            sys.exit(f"ERRO: documento {doc_id} não é um serviço antigo ({meta}). Nada foi alterado.")
    case_meta = by_id.get(CASE_JURIDICO_ID) or {}
    if case_meta.get("tipo") != "caso" or case_meta.get("sector") != "Jurídico":
        sys.exit(f"ERRO: documento {CASE_JURIDICO_ID} não é o caso Jurídico ({case_meta}). Nada foi alterado.")

    existing_new = db.table("documents").select("id").in_("metadata->>tipo", ["preco", "preco_tabela"]).execute().data
    if existing_new:
        sys.exit("ERRO: já existem documentos de preços na base. O script já terá corrido. Nada foi alterado.")

    new_docs = _new_documents()
    case_doc = _case_juridico()

    print("Plano:")
    for d in new_docs:
        print(f"  INSERIR  [{d['metadata']['tipo']}] {d['metadata']['nome']}")
    print(f"  ACTUALIZAR id {CASE_JURIDICO_ID} (caso Jurídico, sem nome de cliente)")
    for doc_id in OLD_SERVICE_IDS:
        print(f"  APAGAR   id {doc_id} ({by_id[doc_id].get('nome')})")

    if not apply:
        print("\nSimulação apenas. Nada foi alterado. Para executar: python rag_fase2b.py --apply")
        return

    oai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def embed(text: str) -> list[float]:
        vector = oai.embeddings.create(model=EMBEDDING_MODEL, input=text).data[0].embedding
        if len(vector) != 1536:
            sys.exit(f"ERRO: embedding com {len(vector)} dimensões (esperado 1536). Parado.")
        return vector

    # 1. Inserir primeiro (a base nunca fica sem serviços)
    for d in new_docs:
        db.table("documents").insert({
            "conteudo": d["conteudo"],
            "metadata": d["metadata"],
            "embedding": embed(d["conteudo"]),
        }).execute()
        print(f"  inserido: {d['metadata']['nome']}")
        time.sleep(0.3)

    # 2. Actualizar o caso Jurídico
    db.table("documents").update({
        "conteudo": case_doc["conteudo"],
        "metadata": case_doc["metadata"],
        "embedding": embed(case_doc["conteudo"]),
    }).eq("id", CASE_JURIDICO_ID).execute()
    print(f"  actualizado: id {CASE_JURIDICO_ID}")

    # 3. Apagar os serviços antigos
    db.table("documents").delete().in_("id", OLD_SERVICE_IDS).execute()
    print(f"  apagados: ids {OLD_SERVICE_IDS[0]} a {OLD_SERVICE_IDS[-1]}")

    print("\n[OK] Fase 2B aplicada na base de conhecimento.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 2B: actualiza a base de conhecimento")
    parser.add_argument("--apply", action="store_true", help="Executa as alterações (sem isto, só simula)")
    main(apply=parser.parse_args().apply)

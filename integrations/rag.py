import logging
from openai import AsyncOpenAI

from .supabase_client import get_supabase

logger = logging.getLogger(__name__)

_oai_client: AsyncOpenAI | None = None


def _get_oai() -> AsyncOpenAI | None:
    global _oai_client
    if _oai_client is None:
        import os
        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            return None
        _oai_client = AsyncOpenAI(api_key=key)
    return _oai_client


async def consultar_conhecimento(
    pergunta: str,
    top_k: int = 4,
    limiar: float = 0.50,
) -> str | None:
    """
    Embede a pergunta e devolve os chunks mais relevantes da tabela documents.
    Retorna None se OPENAI_API_KEY não estiver configurada, se não houver
    resultados acima do limiar, ou se ocorrer qualquer erro.
    """
    client = _get_oai()
    if client is None:
        logger.warning("RAG: OPENAI_API_KEY não configurada — a saltar.")
        return None

    try:
        resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=pergunta,
        )
        embedding = resp.data[0].embedding

        db = get_supabase()
        result = db.rpc("match_documents", {
            "query_embedding": embedding,
            "match_count": top_k,
        }).execute()

        todos = result.data or []
        chunks = [r for r in todos if r.get("similarity", 0) >= limiar]

        logger.info(
            f"RAG: {len(todos)} resultado(s) — {len(chunks)} acima do limiar {limiar} "
            f"| top similarity: {max((r.get('similarity', 0) for r in todos), default=0):.3f}"
        )

        if not chunks:
            return None

        linhas = []
        for r in chunks:
            tipo = r["metadata"].get("tipo", "info").upper()
            linhas.append(f"[{tipo}] {r['conteudo']}")

        return "\n\n".join(linhas)

    except Exception as e:
        logger.error(f"RAG: erro ao consultar conhecimento: {e}")
        return None

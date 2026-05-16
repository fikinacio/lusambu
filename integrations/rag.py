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
    top_k: int = 3,
    limiar: float = 0.70,
) -> str | None:
    """
    Embede a pergunta e devolve os chunks mais relevantes da tabela documents.
    Retorna None se OPENAI_API_KEY não estiver configurada, se não houver
    resultados acima do limiar, ou se ocorrer qualquer erro.
    """
    client = _get_oai()
    if client is None:
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

        chunks = [
            r for r in (result.data or [])
            if r.get("similarity", 0) >= limiar
        ]

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

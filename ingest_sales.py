"""
ingest_sales.py — Ingere documentos de vendas Bisca+ na tabela `documents`.

Complementa o ingest.py com portfólio detalhado com preços, casos com
argumentos de venda, e respostas validadas a objecções.

Pré-requisitos:
  1. rag_migration.sql já executado (tabela `documents` existe)
  2. OPENAI_API_KEY e credenciais Supabase no .env

Uso:
  python ingest_sales.py
  python ingest_sales.py --reset   # apaga documentos de vendas antes de inserir
"""
import argparse
import os
import sys
import time

# Rede corporativa com inspecção TLS — mesma abordagem do ingest.py
import ssl
import httpx

ssl._create_default_https_context = ssl._create_unverified_context

_orig_client_init = httpx.Client.__init__


def _no_ssl_init(self, *args, **kwargs):
    kwargs["verify"] = False
    _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _no_ssl_init


def _load_dotenv(path: str = ".env") -> None:
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

# ---------------------------------------------------------------------------
# Documentos de vendas
# ---------------------------------------------------------------------------

SOURCE_TAG = "bisca_plus_sales_2026"

SALES_CHUNKS: list[dict] = [

    # ── INSTITUCIONAL ──────────────────────────────────────────────────────

    {
        "conteudo": (
            "A Bisca+ (marca da BMST — Bisca Mais Sistemas e Tecnologias) é uma empresa angolana "
            "de automação e inteligência artificial sediada em Luanda. "
            "Especializada em sistemas de agentes autónomos que executam tarefas completas de negócio "
            "sem intervenção humana: atendimento, prospecção, vendas, conteúdo, análise de documentos "
            "e inteligência de mercado. "
            "Todos os sistemas estão em produção com clientes reais em Angola. "
            "Stack técnica: LangGraph, FastAPI, Supabase, Redis, Evolution API (WhatsApp). "
            "Fundador: Fidel Kussunga, Engenheiro de Sistemas pela Universidade do Minho."
        ),
        "metadata": {"tipo": "institucional", "titulo": "Quem é a Bisca+", "source": SOURCE_TAG},
    },

    # ── PORTFÓLIO COM PREÇOS ───────────────────────────────────────────────

    {
        "conteudo": (
            "SOLUÇÃO: Assistente de Atendimento com RAG\n"
            "Atendimento automático 24h/7 dias com base de conhecimento personalizada.\n"
            "Qualifica clientes, responde a perguntas frequentes, encaminha para a equipa.\n"
            "Funciona no WhatsApp. Sectores com casos reais: automóvel, arquitectura, "
            "imobiliário, turismo, jurídico, serviços profissionais.\n"
            "Resultados típicos: zero leads perdidos fora de horário, equipa liberta de FAQ.\n"
            "INVESTIMENTO: Setup 95.000 AOA + 42.000 AOA/mês."
        ),
        "metadata": {"tipo": "portfolio_preco", "titulo": "Assistente de Atendimento RAG", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "SOLUÇÃO: Equipa de Vendas Autónoma\n"
            "Sistema multi-agente que gere o ciclo de vendas completo.\n"
            "Qualificação de leads, follow-up automático, registo no CRM, escalada só para fechar.\n"
            "Canais: WhatsApp, email, LinkedIn. Zero leads sem resposta.\n"
            "INVESTIMENTO: Setup 160.000 AOA + 68.000 AOA/mês."
        ),
        "metadata": {"tipo": "portfolio_preco", "titulo": "Equipa de Vendas Autónoma", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "SOLUÇÃO: Sistema de Prospecção Activa\n"
            "Oito agentes que executam o ciclo completo de prospecção B2B.\n"
            "Pesquisa leads por sector, envia mensagens personalizadas, follow-up automático, "
            "registo CRM, propostas adaptadas, geração de facturas.\n"
            "O responsável só intervém para validar informação crítica ou assinar contrato.\n"
            "INVESTIMENTO: Setup 240.000 AOA + 95.000 AOA/mês."
        ),
        "metadata": {"tipo": "portfolio_preco", "titulo": "Sistema de Prospecção Activa", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "SOLUÇÃO: Pipeline de Conteúdo para Redes Sociais\n"
            "Quatro agentes: pesquisa, escrita, revisão, publicação.\n"
            "Produz e publica conteúdo diário no LinkedIn, Instagram, Facebook.\n"
            "Resultado: presença digital consistente sem ocupar tempo da equipa.\n"
            "INVESTIMENTO: Setup 160.000 AOA + 68.000 AOA/mês."
        ),
        "metadata": {"tipo": "portfolio_preco", "titulo": "Pipeline de Conteúdo Social", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "SOLUÇÃO: Análise de Documentos Jurídicos (RAG Jurídico)\n"
            "Para escritórios de advocacia e departamentos jurídicos.\n"
            "Analisa contratos, extrai cláusulas e prazos, responde a perguntas sobre documentos.\n"
            "Caso real: André Fonseca & Associados — 29 anos de experiência, facturação "
            "e presença digital implementadas em 1 mês.\n"
            "INVESTIMENTO: Setup 200.000 AOA + 80.000 AOA/mês."
        ),
        "metadata": {"tipo": "portfolio_preco", "titulo": "Análise Documental Jurídica", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "SOLUÇÃO: Inteligência de Mercado\n"
            "Agente que monitoriza concorrentes e entrega relatórios estratégicos periódicos.\n"
            "Analisa presença digital, preços, posicionamento; identifica oportunidades e ameaças.\n"
            "Resultado: decisões estratégicas baseadas em dados, não em intuição.\n"
            "INVESTIMENTO: Setup 180.000 AOA + 75.000 AOA/mês."
        ),
        "metadata": {"tipo": "portfolio_preco", "titulo": "Inteligência de Mercado", "source": SOURCE_TAG},
    },

    # ── TABELA DE PREÇOS ──────────────────────────────────────────────────

    {
        "conteudo": (
            "TABELA DE PREÇOS BISCA+ 2026 (em Kwanzas)\n\n"
            "Assistente de Atendimento RAG: Setup 95.000 AOA | Mensalidade 42.000 AOA\n"
            "Equipa de Vendas Autónoma: Setup 160.000 AOA | Mensalidade 68.000 AOA\n"
            "Sistema de Prospecção Activa: Setup 240.000 AOA | Mensalidade 95.000 AOA\n"
            "Pipeline de Conteúdo Social: Setup 160.000 AOA | Mensalidade 68.000 AOA\n"
            "Análise Documental Jurídica: Setup 200.000 AOA | Mensalidade 80.000 AOA\n"
            "Inteligência de Mercado: Setup 180.000 AOA | Mensalidade 75.000 AOA\n"
            "Solução Empresarial (custom): Setup 400.000+ AOA | Mensalidade 150.000+ AOA\n\n"
            "Prazo de implementação: 7 a 15 dias úteis após confirmação.\n"
            "Suporte técnico 7 dias por semana incluído.\n"
            "Pagamento: transferência bancária — Banco BFA ou BAI.\n\n"
            "THRESHOLD DE ESCALADA (interno — não partilhar):\n"
            "Setup > 300.000 AOA ou Mensalidade > 100.000 AOA → notificar Fidel.\n"
            "Qualquer desconto > 10% → notificar Fidel antes de responder."
        ),
        "metadata": {"tipo": "preco_tabela", "titulo": "Tabela de Preços 2026", "source": SOURCE_TAG},
    },

    # ── CASOS COM ARGUMENTO DE VENDA ──────────────────────────────────────

    {
        "conteudo": (
            "CASO: Stand Automóvel\n"
            "Desafio: Consultas chegavam fora de horário sem resposta — leads perdidos para a concorrência.\n"
            "Solução: Assistente RAG 24/7 com catálogo completo: compra/venda, aluguer, manutenção.\n"
            "Encaminha para agendamento presencial quando há intenção de compra confirmada.\n"
            "Resultados: 24/7 disponibilidade, zero leads perdidos fora de horário, mais visitas qualificadas.\n"
            "ARGUMENTO: 'Cada lead que chega fora de horário e não recebe resposta vai "
            "directamente ao stand do lado. Com o nosso sistema isso não acontece.'"
        ),
        "metadata": {"tipo": "caso_vendas", "sector": "Automóvel", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "CASO: Construção Civil e Arquitectura\n"
            "Desafio: Equipa técnica consumia tempo em perguntas repetitivas sobre serviços e portfólio.\n"
            "Solução: Assistente RAG com base de conhecimento de 10+ serviços, qualifica tipo de projecto.\n"
            "Resultados: 24/7 cobertura, zero tempo da equipa em FAQ, técnicos focados em obra.\n"
            "ARGUMENTO: 'Os vossos técnicos custam dinheiro quando estão a responder emails. "
            "O sistema faz isso por eles.'"
        ),
        "metadata": {"tipo": "caso_vendas", "sector": "Construção Civil / Arquitectura", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "CASO: Imobiliário / Avaliação\n"
            "Desafio: Perito a responder manualmente a perguntas técnicas básicas — tempo desperdiçado.\n"
            "Solução: FAQ automatizado com 15+ perguntas frequentes e qualificação de pedidos.\n"
            "Resultados: perito só entra quando o cliente está qualificado, zero tempo em dúvidas básicas.\n"
            "ARGUMENTO: 'O tempo do perito deve estar em avaliações, não em explicar "
            "o processo pela décima vez.'"
        ),
        "metadata": {"tipo": "caso_vendas", "sector": "Imobiliário", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "CASO: Turismo e Agências de Viagem\n"
            "Desafio: Clientes perdidos por falta de resposta fora de horário ou em picos de procura.\n"
            "Solução: Atendimento automatizado 24/7 via WhatsApp, resposta em segundos.\n"
            "Resultados: zero clientes perdidos por falta de resposta, capacidade de atender picos.\n"
            "ARGUMENTO: 'Um turista que não recebe resposta à noite reserva noutro sítio de manhã. "
            "O sistema garante que a resposta chega sempre.'"
        ),
        "metadata": {"tipo": "caso_vendas", "sector": "Turismo", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "CASO: Sector Jurídico\n"
            "Desafio: Advogado com 29 anos de experiência sem presença digital — clientes não o encontravam.\n"
            "Solução: Site institucional com 6 áreas de prática e facturação 100% automatizada.\n"
            "Resultados: presença profissional do zero, facturação automatizada, entregue em 1 mês.\n"
            "ARGUMENTO: 'Um advogado que não aparece online não existe para 90% "
            "dos potenciais clientes hoje.'"
        ),
        "metadata": {"tipo": "caso_vendas", "sector": "Jurídico", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "CASO: Serviços Profissionais\n"
            "Desafio: Profissional liberal perdia clientes por indisponibilidade durante a prestação de serviço.\n"
            "Solução: Atendimento e qualificação automática de leads 24/7.\n"
            "Resultados: 24/7 disponibilidade, qualificação automática, zero perda por indisponibilidade.\n"
            "ARGUMENTO: 'Não podes atender o telefone quando estás com um cliente. "
            "O sistema atende por ti.'"
        ),
        "metadata": {"tipo": "caso_vendas", "sector": "Serviços Profissionais", "source": SOURCE_TAG},
    },

    # ── OBJECÇÕES E RESPOSTAS VALIDADAS ──────────────────────────────────

    {
        "conteudo": (
            "OBJECÇÃO: Preço elevado / 'Está caro' / 'Quanto custa?'\n"
            "Contexto: lead hesita sem ter calculado o retorno.\n"
            "RESPOSTA VALIDADA: 'Depende do que precisas. O que posso dizer é que os nossos clientes "
            "recuperam o investimento no primeiro mês — um atendimento 24/7 substitui pelo menos um "
            "funcionário a tempo parcial, sem faltas, sem férias, sem salário fixo todo o mês. "
            "Qual é o vosso maior custo operacional agora?'\n"
            "TÁCTICA: redirigir para o custo do problema actual. Nunca dar desconto imediato. "
            "Primeiro perceber se é objecção de preço real ou falta de percepção de valor."
        ),
        "metadata": {"tipo": "objeccao_resposta", "nome": "Preço elevado", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "OBJECÇÃO: 'Isso vai tirar emprego à minha equipa' / 'Vou ter de despedir pessoas'\n"
            "Contexto: preocupação legítima e emocional — frequente em Angola.\n"
            "RESPOSTA VALIDADA: 'Não substitui pessoas — liberta-as de tarefas repetitivas para "
            "focarem no que realmente importa. O cliente de arquitectura que temos, a equipa passou "
            "a estar em obra em vez de responder a emails. As pessoas continuam lá, só fazem "
            "trabalho de maior valor.'\n"
            "TÁCTICA: usar caso concreto. Nunca argumentar em abstracto sobre emprego. "
            "Esta objecção raramente converte — reconhecer e avançar."
        ),
        "metadata": {"tipo": "objeccao_resposta", "nome": "Emprego", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "OBJECÇÃO: 'Já temos um sistema' / 'Já temos alguém que trata disso'\n"
            "Contexto: lead defende o status quo, muitas vezes sem sistema real.\n"
            "RESPOSTA VALIDADA: 'Fico contente em ouvir isso. Posso perguntar — esse sistema "
            "responde a clientes fora de horário? Qualifica leads automaticamente? Porque o que "
            "normalmente encontramos é uma ferramenta pontual, não um sistema integrado. "
            "Se já têm tudo isso a funcionar, talvez não precisem de nós mesmo.'\n"
            "TÁCTICA: a última frase baixa a guarda e força honestidade. "
            "Não atacar o sistema actual — fazer perguntas que exponham as lacunas."
        ),
        "metadata": {"tipo": "objeccao_resposta", "nome": "Já temos sistema", "source": SOURCE_TAG},
    },

    {
        "conteudo": (
            "OBJECÇÃO: 'Deixa-me pensar' / 'Não é o momento certo' / 'Talvez mais para a frente'\n"
            "Contexto: lead não rejeita mas adia sem comprometer.\n"
            "RESPOSTA VALIDADA: 'Percebo. Posso perguntar o que está a travar a decisão? "
            "Às vezes é uma dúvida que resolvo agora, outras vezes é mesmo o momento — "
            "e nesse caso marco contigo daqui a 30 dias.'\n"
            "TÁCTICA: não pressionar. Identificar se é objecção real ou falta de informação. "
            "Se for timing, propor data concreta para follow-up em 7 dias."
        ),
        "metadata": {"tipo": "objeccao_resposta", "nome": "Timing / Pensar", "source": SOURCE_TAG},
    },

]


# ---------------------------------------------------------------------------
# Script de ingestão
# ---------------------------------------------------------------------------

def main(reset: bool = False) -> None:
    from openai import OpenAI
    from supabase import create_client

    openai_key = os.getenv("OPENAI_API_KEY", "")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_KEY", "")

    if not openai_key:
        print("ERRO: OPENAI_API_KEY não encontrada no .env")
        sys.exit(1)
    if not supabase_url or not supabase_key:
        print("ERRO: SUPABASE_URL ou SUPABASE_KEY não encontradas no .env")
        sys.exit(1)

    oai = OpenAI(api_key=openai_key, http_client=httpx.Client(verify=False))
    db = create_client(supabase_url, supabase_key)

    if reset:
        print(f"A apagar documentos com source='{SOURCE_TAG}'...")
        db.table("documents").delete().eq("metadata->>source", SOURCE_TAG).execute()
        print("Documentos anteriores apagados.")

    print(f"\nA ingerir {len(SALES_CHUNKS)} documentos de vendas...\n")

    for i, chunk in enumerate(SALES_CHUNKS, 1):
        titulo = chunk["metadata"].get("titulo") or chunk["metadata"].get("sector", f"chunk {i}")
        print(f"  [{i:02d}/{len(SALES_CHUNKS)}] {titulo}...", end=" ", flush=True)

        resp = oai.embeddings.create(
            model="text-embedding-3-small",
            input=chunk["conteudo"],
        )
        embedding = resp.data[0].embedding

        db.table("documents").insert({
            "conteudo": chunk["conteudo"],
            "metadata": chunk["metadata"],
            "embedding": embedding,
        }).execute()

        print("ok")
        time.sleep(0.3)

    print(f"\n[OK] {len(SALES_CHUNKS)} documentos de vendas ingeridos com sucesso.")
    print("\nPara verificar: SELECT count(*), metadata->>'tipo' FROM documents GROUP BY 2;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingere documentos de vendas Bisca+ no Supabase")
    parser.add_argument("--reset", action="store_true", help="Apaga documentos de vendas anteriores")
    args = parser.parse_args()
    main(reset=args.reset)

"""
ingest.py — Ingere o conhecimento BMST na tabela `documents` do Supabase.

Pré-requisitos:
  1. Executar rag_migration.sql no Supabase SQL Editor
  2. OPENAI_API_KEY e credenciais Supabase no .env

Uso:
  python ingest.py
  python ingest.py --reset   # apaga documentos anteriores antes de inserir
"""
import argparse
import os
import ssl
import sys
import time
import httpx

# Rede corporativa com inspecção TLS — força verify=False em todos os clientes httpx
ssl._create_default_https_context = ssl._create_unverified_context

_orig_client_init = httpx.Client.__init__
def _no_ssl_init(self, *args, **kwargs):
    kwargs['verify'] = False
    _orig_client_init(self, *args, **kwargs)
httpx.Client.__init__ = _no_ssl_init


# ---------------------------------------------------------------------------
# Carrega .env (mesma lógica do chat_local.py)
# ---------------------------------------------------------------------------

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
# Conteúdo a ingerir
# ---------------------------------------------------------------------------

CHUNKS: list[dict] = [
    # ---- Serviços (cinco áreas de solução, texto aprovado do site) ----
    {
        "conteudo": (
            "Sistemas Inteligentes e IA (AI & Intelligent Systems): pesquisa nos documentos da empresa; "
            "agentes para tarefas em várias etapas; processamento de documentos; sistemas com vários agentes. "
            "Página: https://bmst.ao/pt/solucoes/sistemas-inteligentes-ia/"
        ),
        "metadata": {"tipo": "servico", "nome": "Sistemas Inteligentes e IA"},
    },
    {
        "conteudo": (
            "Automação e Integração (Automation & Integration): automação de processos; "
            "integração de sistemas (CRM, ERP, APIs); mensagens e WhatsApp; fluxos em n8n. "
            "Página: https://bmst.ao/pt/solucoes/automacao-integracao/"
        ),
        "metadata": {"tipo": "servico", "nome": "Automação e Integração"},
    },
    {
        "conteudo": (
            "Engenharia de Software (Software Engineering): aplicações web; sistemas empresariais; "
            "backend e APIs; frontend e experiência de utilização. "
            "Página: https://bmst.ao/pt/solucoes/engenharia-de-software/"
        ),
        "metadata": {"tipo": "servico", "nome": "Engenharia de Software"},
    },
    {
        "conteudo": (
            "Inteligência de Dados (Data Intelligence): engenharia de dados; painéis de gestão; "
            "relatórios automáticos; análise e apoio à decisão. "
            "Página: https://bmst.ao/pt/solucoes/inteligencia-de-dados/"
        ),
        "metadata": {"tipo": "servico", "nome": "Inteligência de Dados"},
    },
    {
        "conteudo": (
            "Cibersegurança (Cybersecurity): auditoria de segurança; avaliação de vulnerabilidades; "
            "reforço de sistemas; segurança de aplicações; consultoria. "
            "Página: https://bmst.ao/pt/solucoes/ciberseguranca/"
        ),
        "metadata": {"tipo": "servico", "nome": "Cibersegurança"},
    },
    # ---- Preços (em Kwanzas) ----
    {
        "conteudo": (
            "Assistente de Atendimento com base de conhecimento (área: Automação e Integração). "
            "Atendimento automático 24 horas por dia no WhatsApp, com base de conhecimento do cliente. "
            "Qualifica clientes, responde a perguntas frequentes e encaminha para a equipa. "
            "Investimento: setup de 95.000 AOA e mensalidade de 42.000 AOA."
        ),
        "metadata": {"tipo": "preco", "nome": "Assistente de Atendimento", "area": "Automação e Integração"},
    },
    {
        "conteudo": (
            "Equipa de Vendas Autónoma (área: Sistemas Inteligentes e IA). "
            "Sistema com vários agentes que gere o ciclo de vendas: qualificação de leads, follow-up "
            "automático, registo no CRM e passagem à equipa só para fechar. Canais: WhatsApp, email e LinkedIn. "
            "Investimento: setup de 160.000 AOA e mensalidade de 68.000 AOA."
        ),
        "metadata": {"tipo": "preco", "nome": "Equipa de Vendas Autónoma", "area": "Sistemas Inteligentes e IA"},
    },
    {
        "conteudo": (
            "Sistema de Prospecção Activa (área: Sistemas Inteligentes e IA). "
            "Agentes que executam o ciclo de prospecção B2B: pesquisa de leads por sector, mensagens "
            "personalizadas, follow-up, registo no CRM, propostas e facturas. "
            "Investimento: setup de 240.000 AOA e mensalidade de 95.000 AOA."
        ),
        "metadata": {"tipo": "preco", "nome": "Sistema de Prospecção Activa", "area": "Sistemas Inteligentes e IA"},
    },
    {
        "conteudo": (
            "Pipeline de Conteúdo para Redes Sociais (área: Automação e Integração). "
            "Agentes que pesquisam, escrevem, revêem e publicam conteúdo no LinkedIn, Instagram e Facebook. "
            "Investimento: setup de 160.000 AOA e mensalidade de 68.000 AOA."
        ),
        "metadata": {"tipo": "preco", "nome": "Pipeline de Conteúdo Social", "area": "Automação e Integração"},
    },
    {
        "conteudo": (
            "Análise de Documentos Jurídicos (área: Sistemas Inteligentes e IA, processamento de documentos). "
            "Para escritórios de advocacia e departamentos jurídicos: analisa contratos, extrai cláusulas "
            "e prazos e responde a perguntas sobre os documentos. "
            "Investimento: setup de 200.000 AOA e mensalidade de 80.000 AOA."
        ),
        "metadata": {"tipo": "preco", "nome": "Análise Documental Jurídica", "area": "Sistemas Inteligentes e IA"},
    },
    {
        "conteudo": (
            "Inteligência de Mercado (área: Inteligência de Dados). "
            "Agente que acompanha concorrentes e entrega relatórios periódicos sobre presença digital, "
            "preços e posicionamento. "
            "Investimento: setup de 180.000 AOA e mensalidade de 75.000 AOA."
        ),
        "metadata": {"tipo": "preco", "nome": "Inteligência de Mercado", "area": "Inteligência de Dados"},
    },
    {
        "conteudo": (
            "Solução Empresarial à medida (área: Engenharia de Software). "
            "Sistema desenhado para o processo específico da empresa, dimensionado em reunião. "
            "Investimento: a partir de 400.000 AOA de setup e 150.000 AOA de mensalidade."
        ),
        "metadata": {"tipo": "preco", "nome": "Solução Empresarial à medida", "area": "Engenharia de Software"},
    },
    {
        "conteudo": (
            "Tabela de preços BMST (em Kwanzas, setup e mensalidade): "
            "Assistente de Atendimento 95.000 e 42.000 AOA; "
            "Equipa de Vendas Autónoma 160.000 e 68.000 AOA; "
            "Sistema de Prospecção Activa 240.000 e 95.000 AOA; "
            "Pipeline de Conteúdo Social 160.000 e 68.000 AOA; "
            "Análise Documental Jurídica 200.000 e 80.000 AOA; "
            "Inteligência de Mercado 180.000 e 75.000 AOA; "
            "Solução Empresarial à medida a partir de 400.000 e 150.000 AOA. "
            "Funcionalidades fora desta tabela não têm preço tabelado."
        ),
        "metadata": {"tipo": "preco_tabela", "nome": "Tabela de preços BMST"},
    },
    # ---- Casos de estudo ----
    {
        "conteudo": (
            "Caso Jurídico — Escritório de advocacia: escritório de advogados sem presença digital. "
            "Implementámos presença digital do zero e facturação 100% automatizada. "
            "Resultado entregue em 1 mês. O advogado deixou de gastar tempo com tarefas administrativas "
            "e passou a receber clientes qualificados automaticamente."
        ),
        "metadata": {"tipo": "caso", "sector": "Jurídico"},
    },
    {
        "conteudo": (
            "Caso Finanças — Co-piloto de trading: sistema de monitorização de mercados financeiros. "
            "Alertas em tempo real para oportunidades e riscos, "
            "com redução drástica do tempo de análise manual. "
            "O trader foca-se nas decisões — o agente faz a vigilância contínua."
        ),
        "metadata": {"tipo": "caso", "sector": "Finanças"},
    },
    {
        "conteudo": (
            "Caso Serviços Profissionais — Tradutor de documentos: freelancer que perdia clientes "
            "por não estar disponível fora de horas. "
            "Implementámos captação de clientes 24/7 e qualificação automática de pedidos. "
            "Resultado: zero perdas por indisponibilidade, pipeline de trabalho previsível."
        ),
        "metadata": {"tipo": "caso", "sector": "Serviços Profissionais"},
    },
    {
        "conteudo": (
            "Caso Construção Civil — Empresa de arquitectura: equipa sobrecarregada com perguntas "
            "repetitivas de clientes sobre serviços, prazos e processos. "
            "Implementámos atendimento automatizado com base de conhecimento de 10+ serviços. "
            "Resultado: zero tempo da equipa técnica em FAQ, mais foco no trabalho criativo."
        ),
        "metadata": {"tipo": "caso", "sector": "Construção Civil / Arquitectura"},
    },
    {
        "conteudo": (
            "Caso Automóvel — Stand automóvel: leads que chegavam fora de horário eram perdidos. "
            "Implementámos agente 24/7 que converte consultas em visitas qualificadas ao stand. "
            "Resultado: zero leads perdidos fora de horário, equipa de vendas só recebe "
            "contactos já qualificados e com interesse confirmado."
        ),
        "metadata": {"tipo": "caso", "sector": "Automóvel"},
    },
    {
        "conteudo": (
            "Caso Imobiliário — Avaliação imobiliária: perito gastava muito tempo em triagem inicial. "
            "Implementámos fluxo automático de 15+ perguntas de qualificação antes da avaliação. "
            "Resultado: o perito só entra em acção quando o cliente está totalmente qualificado, "
            "focado exclusivamente no trabalho técnico de avaliação."
        ),
        "metadata": {"tipo": "caso", "sector": "Imobiliário"},
    },
    {
        "conteudo": (
            "Caso Turismo — Agência de viagens: clientes que não recebiam resposta imediata "
            "iam à concorrência. "
            "Implementámos resposta automática em segundos, disponível 24/7, "
            "com qualificação de pedidos e recolha de preferências. "
            "Resultado: zero clientes perdidos por falta de resposta, capacidade de atender "
            "picos de procura sem aumentar equipa."
        ),
        "metadata": {"tipo": "caso", "sector": "Turismo"},
    },
]

# ---------------------------------------------------------------------------
# Ingestão
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
        print("A apagar documentos anteriores...")
        db.table("documents").delete().neq("id", 0).execute()
        print("Tabela limpa.")

    print(f"\nA ingerir {len(CHUNKS)} chunks...\n")

    for i, chunk in enumerate(CHUNKS, 1):
        nome = chunk["metadata"].get("nome") or chunk["metadata"].get("sector", f"chunk {i}")
        print(f"  [{i:02d}/{len(CHUNKS)}] {nome}...", end=" ", flush=True)

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
        time.sleep(0.3)  # evita rate limiting

    print(f"\n[OK] {len(CHUNKS)} chunks ingeridos com sucesso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingere conhecimento BMST no Supabase")
    parser.add_argument("--reset", action="store_true", help="Apaga documentos anteriores antes de inserir")
    args = parser.parse_args()
    main(reset=args.reset)

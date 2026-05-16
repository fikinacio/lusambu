"""
ingest.py — Ingere o conhecimento Bisca+ na tabela `documents` do Supabase.

Pré-requisitos:
  1. Executar rag_migration.sql no Supabase SQL Editor
  2. OPENAI_API_KEY e credenciais Supabase no .env

Uso:
  python ingest.py
  python ingest.py --reset   # apaga documentos anteriores antes de inserir
"""
import argparse
import os
import sys
import time


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
    # ---- Serviços ----
    {
        "conteudo": (
            "Automação de Processos: fluxos automatizados sem IA. "
            "Inclui automação simples de tarefas repetitivas, automação multi-sistema "
            "e integrações via API e Webhook. Ideal para empresas que querem eliminar "
            "trabalho manual sem depender de inteligência artificial."
        ),
        "metadata": {"tipo": "servico", "nome": "Automação de Processos"},
    },
    {
        "conteudo": (
            "Automação com IA: fluxos inteligentes com modelos de linguagem e visão. "
            "Capacidades: classificação e routing automático de pedidos, extracção de dados "
            "de documentos (facturas, contratos, formulários), resumos e relatórios automáticos. "
            "Reduz erros e tempo de processamento em operações baseadas em documentos."
        ),
        "metadata": {"tipo": "servico", "nome": "Automação com IA"},
    },
    {
        "conteudo": (
            "Chatbots & Assistentes IA: sistemas conversacionais disponíveis 24 horas por dia, "
            "7 dias por semana, para WhatsApp, Telegram e Web. "
            "Casos de uso: atendimento ao cliente, vendas e qualificação de leads, "
            "assistente interno para equipas. Eliminam perdas de negócio por indisponibilidade."
        ),
        "metadata": {"tipo": "servico", "nome": "Chatbots & Assistentes IA"},
    },
    {
        "conteudo": (
            "Agentes de IA Autónomos: sistemas que executam tarefas complexas de forma autónoma, "
            "sem intervenção humana para cada passo. "
            "Aplicações: monitorização proactiva de sistemas ou mercados, "
            "vendas e follow-up automático de leads, suporte técnico de nível 1. "
            "Funcionam como um colaborador digital que nunca para."
        ),
        "metadata": {"tipo": "servico", "nome": "Agentes de IA Autónomos"},
    },
    {
        "conteudo": (
            "Equipas de Agentes Orquestradas (multi-agente): múltiplos agentes de IA a trabalhar "
            "em conjunto para processos complexos. "
            "Exemplos: gestão completa de operações, onboarding automatizado de novos clientes, "
            "monitorização financeira com alertas e relatórios. "
            "Para empresas que precisam de automação em vários departamentos em simultâneo."
        ),
        "metadata": {"tipo": "servico", "nome": "Equipas de Agentes Orquestradas"},
    },
    {
        "conteudo": (
            "Dados & Business Intelligence: infra-estrutura de dados para decisão. "
            "Inclui pipelines ETL para mover e transformar dados entre sistemas, "
            "data warehouse centralizado e dashboards em tempo real. "
            "Transforma dados dispersos em visibilidade operacional clara."
        ),
        "metadata": {"tipo": "servico", "nome": "Dados & Business Intelligence"},
    },
    {
        "conteudo": (
            "Infraestrutura & Cibersegurança: base técnica para operar com segurança. "
            "Cobre configuração e gestão de servidores, segurança de APIs e integrações, "
            "backup automatizado e planos de continuidade de negócio. "
            "Para empresas que precisam de garantias de uptime e protecção de dados."
        ),
        "metadata": {"tipo": "servico", "nome": "Infraestrutura & Cibersegurança"},
    },
    {
        "conteudo": (
            "Formação & Consultoria: capacitação interna de equipas. "
            "Workshops presenciais de automação e IA (4 horas cada, práticos e adaptados ao sector). "
            "Diagnóstico de automação: mapeamos os processos da empresa e identificamos "
            "onde a automação traz maior ROI. Ideal como primeiro passo antes de implementar."
        ),
        "metadata": {"tipo": "servico", "nome": "Formação & Consultoria"},
    },
    {
        "conteudo": (
            "Retainer — Parceiro Contínuo: acompanhamento mensal para empresas que já automatizaram. "
            "Inclui monitorização contínua dos sistemas implementados, manutenção e ajustes, "
            "e relatório mensal de ROI com métricas de impacto. "
            "Garante que a automação continua a funcionar e a gerar valor ao longo do tempo."
        ),
        "metadata": {"tipo": "servico", "nome": "Retainer (Parceiro Contínuo)"},
    },
    # ---- Casos de estudo ----
    {
        "conteudo": (
            "Caso Jurídico — Advogado André Fonseca: escritório de advogados sem presença digital. "
            "Implementámos presença digital do zero e facturação 100% automatizada. "
            "Resultado entregue em 1 mês. O advogado deixou de gastar tempo com tarefas administrativas "
            "e passou a receber clientes qualificados automaticamente."
        ),
        "metadata": {"tipo": "caso", "sector": "Jurídico", "cliente": "Advogado André Fonseca"},
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

    oai = OpenAI(api_key=openai_key)
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

    print(f"\n✓ {len(CHUNKS)} chunks ingeridos com sucesso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingere conhecimento Bisca+ no Supabase")
    parser.add_argument("--reset", action="store_true", help="Apaga documentos anteriores antes de inserir")
    args = parser.parse_args()
    main(reset=args.reset)

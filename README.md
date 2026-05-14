# Lusambu — Agente de Vendas Bisca+

Agente de vendas autónomo via WhatsApp para a [Bisca+](https://biscaplus.com), empresa angolana especialista em automação com IA para PMEs.

A Lusambu qualifica leads, faz pitch adaptado ao sector, gere objecções e escala para o especialista humano quando necessário.

---

## Como funciona

```
WhatsApp → Evolution API → /webhook/lusambu → FastAPI
                                                  ↓
                                          LangGraph (Claude)
                                          ├── qualify  → percebe negócio + dor
                                          ├── pitch    → caso concreto por sector
                                          ├── objection → gere até 2 objecções
                                          ├── discard  → lead sem empresa → despedida
                                          └── escalate → notifica especialista humano
```

Estado por conversa persistido em Redis. Leads guardados em Supabase.

---

## Stack

| Componente | Tecnologia |
|---|---|
| API / Webhook | FastAPI + uvicorn |
| Orquestração | LangGraph |
| LLM | Claude Sonnet 4.6 (Anthropic) |
| WhatsApp | Evolution API |
| Base de dados | Supabase (PostgreSQL) |
| Estado | Redis (LangGraph AsyncRedisSaver) |

---

## Configuração

Copia `.env.example` para `.env` e preenche as variáveis:

```bash
cp .env.example .env
```

| Variável | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API Anthropic |
| `SUPABASE_URL` | URL do projecto Supabase |
| `SUPABASE_KEY` | Service role key do Supabase |
| `REDIS_URL` | URL de ligação ao Redis |
| `EVOLUTION_API_URL` | URL base da Evolution API |
| `EVOLUTION_API_KEY` | API key da Evolution API |
| `EVOLUTION_INSTANCE` | Nome da instância WhatsApp |
| `FIDEL_WHATSAPP_NUMBER` | Número do especialista humano para escalações |

---

## Testar localmente

Só precisas do `ANTHROPIC_API_KEY`. Redis, WhatsApp e Supabase são substituídos por mocks que imprimem no terminal.

```bash
pip install -r requirements.txt
python chat_local.py
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Lusambu — Modo Local
  Ctrl+C para sair
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tu: Olá, tenho uma agência imobiliária em Luanda
Lusambu → Olá! Que bom falar contigo...
```

---

## Base de dados (Supabase)

Corre o script SQL no Supabase SQL Editor antes do primeiro deploy:

```sql
-- supabase_schema.sql
```

Ou vai a **SQL Editor** no Supabase e cola o conteúdo de [`supabase_schema.sql`](supabase_schema.sql).

---

## Deploy (EasyPanel)

### 1. Criar serviço

No EasyPanel:
- `+ Service → App`
- Source: GitHub → `fikinacio/lusambu` → branch `main`
- Build: Dockerfile
- Port: `8000`
- Domain: `lusambu.biscaplus.com` + TLS activado

### 2. Variáveis de ambiente

Na aba **Environment** do serviço, define todas as variáveis do `.env`.

Para o Redis interno do EasyPanel usa o hostname do serviço:
```
REDIS_URL=redis://<nome-do-serviço-redis>:6379
```

### 3. Verificar deploy

```
GET https://lusambu.biscaplus.com/health
→ {"status":"ok","agent":"Lusambu"}
```

### 4. Configurar webhook na Evolution API

```bash
curl -X POST "https://evolution.biscaplus.com/webhook/set/bmst" \
  -H "apikey: <EVOLUTION_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://lusambu.biscaplus.com/webhook/lusambu",
    "webhook_by_events": false,
    "events": ["MESSAGES_UPSERT"]
  }'
```

---

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes unitários não precisam de API keys reais — o LLM é mockado.

---

## Estrutura

```
lusambu/
├── main.py                  # FastAPI app + webhook
├── config.py                # Configuração via pydantic-settings
├── agent/
│   ├── graph.py             # Grafo LangGraph
│   ├── nodes.py             # Nós: lusambu, discard, escalate
│   ├── prompts.py           # System prompt + prompt de extracção
│   └── state.py             # LusambuState + LeadInfo
├── integrations/
│   ├── evolution.py         # Envio de mensagens WhatsApp
│   └── supabase_client.py   # Upsert de leads
├── tests/                   # Testes unitários e de integração
├── chat_local.py            # Modo local para testes sem infra
├── supabase_schema.sql      # Schema da tabela lusambu_leads
├── Dockerfile
└── .env.example
```

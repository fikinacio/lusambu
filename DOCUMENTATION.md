# Lusambu — Technical Documentation

**Version:** 1.0  
**Stack:** Python 3.12 · LangGraph · Claude Sonnet · FastAPI · Supabase · Evolution API · Fly.io  
**Language:** Portuguese (European) with Angolan warmth  
**Purpose:** Autonomous WhatsApp sales agent for BMST, an Angolan AI automation company

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Agent State Machine](#4-agent-state-machine)
5. [Conversation Stages](#5-conversation-stages)
6. [Core Components](#6-core-components)
7. [Database Design](#7-database-design)
8. [RAG Knowledge Base](#8-rag-knowledge-base)
9. [Dashboard](#9-dashboard)
10. [Automated Follow-up](#10-automated-follow-up)
11. [Deployment](#11-deployment)
12. [Configuration Reference](#12-configuration-reference)
13. [Local Development](#13-local-development)
14. [Testing](#14-testing)
15. [Known Constraints & Design Decisions](#15-known-constraints--design-decisions)

---

## 1. Project Overview

Lusambu is a fully autonomous WhatsApp sales agent built for **BMST Sistemas e Tecnologias**, an Angolan company that sells AI automation solutions to SMEs.

The agent handles the entire sales cycle end-to-end without human intervention:

```
Lead sends WhatsApp message
        ↓
Lusambu qualifies the business
        ↓
Lusambu delivers an adapted pitch
        ↓
Lusambu handles objections (up to 2)
        ↓
Lusambu closes with Calendly scheduling link
        ↓
Fidel (human specialist) receives full lead summary
```

The agent is persona-locked: it presents itself as *Lusambu*, a human sales consultant. It never reveals it is an AI. It speaks European Portuguese with natural Angolan warmth and is deliberately non-sycophantic — no "Of course!", "Great!", or "Sure thing!".

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Fly.io (CDG region)                       │
│                                                                  │
│  ┌──────────────┐     ┌─────────────────────────────────────┐   │
│  │   FastAPI    │────▶│          LangGraph Agent             │   │
│  │  (uvicorn)   │     │                                      │   │
│  │              │     │  lusambu_node ──▶ discard_node       │   │
│  │  POST        │     │        │                             │   │
│  │  /webhook/   │     │        └────────▶ escalate_node      │   │
│  │  lusambu     │     │                                      │   │
│  │              │     │  Checkpointer: SQLite (/data)        │   │
│  │  GET         │     └─────────────────────────────────────┘   │
│  │  /dashboard  │                    │                           │
│  │  /health     │                    │                           │
│  └──────────────┘                    ▼                           │
│         │                   ┌─────────────────┐                  │
│         │                   │  Claude Sonnet   │                  │
│         │                   │  (Anthropic API) │                  │
│         │                   └─────────────────┘                  │
│         │                                                         │
└─────────┼───────────────────────────────────────────────────────┘
          │
          ├──▶ Evolution API ──▶ WhatsApp (send messages)
          │    (biscaplus instance)
          │
          ├──▶ Supabase (lead data + pgvector RAG)
          │
          └──▶ OpenAI API (text-embedding-3-small, RAG only)
```

### Request Flow

1. A WhatsApp user sends a message to the BMST number.
2. Evolution API forwards it to `POST /webhook/lusambu` as a JSON payload.
3. FastAPI parses the payload and fires `asyncio.create_task(_process_message(...))`, returning `{"status":"processing"}` immediately (non-blocking, Evolution sees 200 OK).
4. `_process_message` invokes the LangGraph graph, which persists state per `thread_id = whatsapp_number` in SQLite.
5. `lusambu_node` runs: RAG lookup → LLM response → lead extraction → stage routing.
6. The response is sent back via Evolution API's `sendText` endpoint.
7. Lead data is upserted to Supabase.

---

## 3. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Runtime** | Python 3.12 | Core language |
| **Web framework** | FastAPI + Uvicorn | Webhook receiver, dashboard, health check |
| **AI framework** | LangGraph 0.2+ | Stateful agent graph with persistence |
| **LLM** | Claude Sonnet 4.6 (`claude-sonnet-4-6`) | Conversation + lead extraction |
| **Embeddings** | OpenAI `text-embedding-3-small` | RAG vector search |
| **State persistence** | SQLite via `langgraph-checkpoint-sqlite` | Per-lead conversation memory |
| **Database** | Supabase (PostgreSQL + pgvector) | Lead records + RAG document store |
| **WhatsApp** | Evolution API v2.3+ | Inbound webhooks + outbound messages |
| **Hosting** | Fly.io (CDG — Paris) | Production deployment |
| **CI/CD** | GitHub Actions | Auto-deploy on push to `main` |
| **Scheduler** | APScheduler (AsyncIOScheduler) | Hourly follow-up job |
| **Config** | pydantic-settings | `.env` file + environment variables |

---

## 4. Agent State Machine

The agent is modelled as a LangGraph `StateGraph` with three nodes and conditional routing.

### Graph Structure

```
                    ┌──────────────┐
                    │  [ENTRY]     │
                    │ lusambu_node │
                    └──────┬───────┘
                           │  _router(state.stage)
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        "discard"        END        "escalate"
              │                         │
     ┌────────┴──────┐       ┌──────────┴────────┐
     │  discard_node │       │  escalate_node    │
     └────────┬──────┘       └──────────┬────────┘
              │                         │
              ▼                         ▼
            END                       END
```

### State Schema (`LusambuState`)

```python
class LusambuState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # full conversation history
    whatsapp_number: str        # phone number (thread identity)
    lead_info: LeadInfo         # extracted lead data (name, company, sector, etc.)
    stage: str                  # current stage (see §5)
    objection_count: int        # number of objections handled
    turn_count: int             # total conversation turns
    message_offset: int         # index to ignore old messages on re-entry
    prompt_variant: str         # A/B test variant ("A" or "B")
    escalation_reason: str      # human-readable reason for escalation
    fidel_notified: bool        # whether Fidel received the lead summary
    data_confirmed: bool        # lead confirmed their name/company (sticky)
    calendly_sent: bool         # Calendly link was already sent
```

`LeadInfo` is extracted from the conversation by a second LLM call (zero-temperature) after each turn:

```python
class LeadInfo(TypedDict, total=False):
    name: Optional[str]
    has_business: Optional[bool]   # None = unknown, True = yes, False = no
    company: Optional[str]
    sector: Optional[str]
    pain_point: Optional[str]
    size: Optional[str]
    scheduled_time: Optional[str]
    classification: str            # hot | warm | cold | unknown
    is_objecting: bool
    wants_human: bool
    ready_to_close: bool
    confirms_data: bool            # transient — not persisted to DB
```

### Stage Routing Logic (`_determine_stage`)

```
has_business == False          → "discard"
turn_count >= 12               → "escalate"
wants_human OR objections >= 2 → "escalate"
ready_to_close:
  └─ missing name or company   → "closing"
  └─ data not confirmed        → "closing"
  └─ Calendly not sent         → "closing"
  └─ all done                  → "escalate" (hand off to Fidel)
is_objecting                   → "objection"
sector AND pain_point          → "pitch"
default                        → "qualify"
```

---

## 5. Conversation Stages

### `qualify`
Default starting stage. Lusambu greets naturally and asks one question at a time to understand the business. Required outputs: `sector`, `pain_point`.

### `pitch`
Two A/B variants assigned randomly on first entry to pitch stage:
- **Variant A** — leads with a concrete result from a client in the same sector (case study approach)
- **Variant B** — quantifies the problem first ("How many hours/week does your team spend on this?") then presents the solution

The variant is stored in `prompt_variant` and `lusambu_leads.prompt_variant` for analysis.

### `objection`
Handles standard objections with predefined response framings (price, doubt, "I'll think about it", existing systems, distrust of AI). Escalates to Fidel after 2 objections from the same lead.

### `closing`
Three sub-stages managed without human intervention:

1. **Data collection** — asks for name and company in one message
2. **Confirmation** — presents a formatted summary (`👤 Name`, `🏢 Company`) and asks "Is everything correct?"
3. **Calendly dispatch** — when `data_confirmed = True`, sends the scheduling link without calling the LLM

The Calendly link is sent directly by the system (no LLM needed), then the conversation escalates to Fidel for follow-up after the scheduled call.

### `discard`
Lead has no business. Lusambu sends a polite farewell and sets `status = "descartado"` in the database.

### `escalate`
Fidel receives a full WhatsApp summary with lead name, company, sector, pain point, classification, and reason. Lead receives a handoff message (unless Calendly was already sent).

---

## 6. Core Components

### `main.py` — Application Entry Point

- FastAPI app with `lifespan` context manager
- Initialises LangGraph graph with SQLite checkpointer at startup
- Starts APScheduler for hourly follow-up job
- Routes: `POST /webhook/lusambu`, `GET /health`, `GET /dashboard`, `GET /dashboard/data`

**Webhook parser** (`_parse_evolution_webhook`):
- Filters out `fromMe = true` messages (bot's own outbound messages)
- Extracts `remoteJid` (phone number) and `conversation`/`extendedTextMessage.text`
- Returns `(None, None)` on any failure — silent ignore

**Re-entry logic** (`_process_message`):
- If lead's last stage was `"end"`, creates a fresh state with `message_offset` set to the length of the old conversation, so the LLM ignores previous history
- If lead has an active conversation, appends the new message to existing state
- If new lead, creates a blank initial state

### `agent/nodes.py` — Agent Logic

**`lusambu_node`** — the main node, called on every message:
1. Increments turn counter; increments objection counter if currently in `objection` stage
2. Assigns A/B pitch variant if entering pitch for the first time
3. Extracts `LeadInfo` from conversation (pre-response extraction)
4. Checks if the Calendly fast-path applies (closing + data complete + confirmed + not sent)
5. If Calendly path: sends link directly, skips LLM, updates state and DB
6. Otherwise: runs RAG lookup on the last human message
7. Formats system prompt with current stage, lead info, objection count, A/B variant, pitch instructions, and optional RAG context
8. Calls LLM for response
9. Sends typing indicator + human-like delay (3–8 seconds) + message
10. Re-extracts `LeadInfo` with LLM response included
11. Determines next stage
12. Upserts lead to Supabase
13. Returns updated state

**`discard_node`** — sends farewell message, marks lead as discarded.

**`escalate_node`** — sends Fidel a WhatsApp summary with emoji classification and reason. Sends handoff message to lead (unless Calendly already sent). Idempotent: `fidel_notified` flag prevents double-notification.

### `agent/prompts.py` — Prompt Templates

**`SYSTEM_PROMPT`** — persona definition, conversation rules, objection framings, closing instructions. Dynamically populated with:
- `{stage}` — current stage
- `{lead_info}` — extracted JSON
- `{objection_count}` — number of objections
- `{prompt_variant}` — A or B
- `{pitch_instructions}` — either `PITCH_A` or `PITCH_B` text

**`PITCH_A`** — concrete results by sector (case study examples for commerce, real estate, professional services, hospitality, logistics)

**`PITCH_B`** — diagnostic approach: quantify the problem before presenting the solution

**`EXTRACTION_PROMPT`** — strict JSON extraction instructions with precise criteria for each field, including explicit examples of what does and does not count as `ready_to_close`, `wants_human`, `confirms_data`.

### `integrations/evolution.py` — WhatsApp Messaging

Three async functions:
- `send_whatsapp_message(number, text)` — sends a text message via Evolution API's `/message/sendText/{instance}` endpoint
- `send_typing_indicator(number)` — fires a "composing" presence signal before each message (best-effort, never blocks)
- `notify_fidel(message)` — sends a message to the configured `FIDEL_WHATSAPP_NUMBER`

### `integrations/supabase_client.py` — Database

- `upsert_lead(data)` — upserts to `lusambu_leads` on `whatsapp` conflict. Filters `_TRANSIENT_FIELDS = {"confirms_data"}` to avoid HTTP 400 from missing DB column
- `get_stale_leads(hours=24)` — returns active leads with no contact in the last N hours and fewer than 2 follow-ups
- `get_all_leads()` — returns all leads ordered by `last_contact_at` for the dashboard
- `increment_followup(whatsapp)` — calls a Supabase RPC to atomically increment `followup_count`

### `integrations/rag.py` — Knowledge Retrieval

Async function `consultar_conhecimento(pergunta, top_k=4, limiar=0.50)`:
1. Lazy-initialises OpenAI async client (returns `None` if `OPENAI_API_KEY` not set)
2. Embeds the user's last message using `text-embedding-3-small`
3. Calls Supabase RPC `match_documents` with pgvector similarity search
4. Filters results by cosine similarity threshold (0.50)
5. Returns formatted string with `[TIPO] content` blocks, or `None` if no relevant results

RAG is skipped entirely for stages `closing`, `discard`, `escalate`, and `end`.

---

## 7. Database Design

### `lusambu_leads` table (Supabase)

| Column | Type | Description |
|--------|------|-------------|
| `whatsapp` | text (PK) | Lead's phone number |
| `name` | text | Full name |
| `company` | text | Company name |
| `sector` | text | Business sector |
| `pain_point` | text | Main operational pain |
| `size` | text | Company size estimate |
| `classification` | text | `hot`, `warm`, `cold`, `unknown` |
| `stage` | text | Last known conversation stage |
| `status` | text | `escalado`, `descartado`, or null |
| `followup_count` | int | Number of follow-up messages sent |
| `last_contact_at` | timestamptz | Last interaction timestamp |
| `prompt_variant` | text | A/B pitch variant used |

### `documents` table (Supabase, pgvector)

| Column | Type | Description |
|--------|------|-------------|
| `id` | int (PK) | Auto-increment |
| `conteudo` | text | Document text chunk |
| `metadata` | jsonb | `{tipo: "servico"/"caso", nome/sector/cliente}` |
| `embedding` | vector(1536) | OpenAI embedding |

**RPC functions:**
- `match_documents(query_embedding, match_count)` — returns rows ordered by cosine similarity
- `increment_followup_count(p_whatsapp)` — atomically increments `followup_count`

### Conversation State (SQLite — `/data/checkpoints.sqlite`)

Managed entirely by LangGraph's `AsyncSqliteSaver`. Each WhatsApp number is a `thread_id`. The full message history and all state fields are persisted automatically between turns. The volume file at `/data` is a Fly.io persistent volume that survives machine restarts.

---

## 8. RAG Knowledge Base

### Purpose

Provides Lusambu with verified, specific knowledge about BMST services and client case studies during pitch and objection stages, without hallucination.

### Content (16 chunks)

**Services (9 chunks):**
- Process Automation (no-AI workflows)
- AI Automation (LLM + vision models)
- Chatbots & AI Assistants (WhatsApp, Telegram, Web)
- Autonomous AI Agents
- Orchestrated Agent Teams (multi-agent)
- Data & Business Intelligence
- Infrastructure & Cybersecurity
- Training & Consulting
- Retainer (Continuous Partner)

**Case Studies (7 chunks):**
- Law firm (digital presence + automated invoicing)
- Finance (trading co-pilot with real-time alerts)
- Professional Services (24/7 lead capture for freelancer)
- Architecture firm (automated FAQ handling)
- Car dealership (out-of-hours lead conversion)
- Real estate (automated 15-question pre-qualification)
- Travel agency (instant 24/7 response, zero lost clients)

### Ingestion Pipeline

Run once (or after content updates):

```bash
python ingest.py          # add new chunks
python ingest.py --reset  # clear all and re-ingest
```

The script embeds each chunk using `text-embedding-3-small` and inserts into Supabase with a 0.3s rate-limit delay between calls.

### Similarity Thresholds

Tested similarity scores with real user queries:
- "automatizacao whatsapp" → 0.559 (captured at threshold 0.50) ✅
- "CRM vendas Angola" → 0.408 (below threshold, correctly excluded)
- "quanto custa" → 0.275 (pricing not in KB, correctly excluded)

The threshold of 0.50 balances precision (avoiding irrelevant results) with recall (capturing genuinely relevant service descriptions).

---

## 9. Dashboard

**URL:** `https://lusambu.fly.dev/dashboard?key=<DASHBOARD_KEY>`

A single-page HTML dashboard served from `/dashboard` that polls `/dashboard/data` every 30 seconds via JavaScript `fetch`. No server-side rendering after initial load.

**Metrics:**
- Total leads
- Hot leads (🔥)
- Warm leads (🟡)
- Escalated leads

**Lead table columns:** Name, Company, Sector, Classification (badge), Stage (badge), Pain Point, WhatsApp, Last Contact, Follow-ups, Pitch Variant (A/B)

**Security:** Protected by `DASHBOARD_KEY` query parameter. Requests with a wrong or missing key receive HTTP 403.

**Data endpoint:** `GET /dashboard/data?key=<KEY>` returns pure JSON, allowing external integrations or BI tools to consume the lead pipeline data.

---

## 10. Automated Follow-up

An APScheduler job runs every hour (`interval`, `hours=1`). It calls `get_stale_leads(hours=24)` to find leads who:
- Have not been contacted in the last 24 hours
- Have fewer than 2 follow-ups sent
- Are not discarded or escalated

For each stale lead, it sends a stage-appropriate follow-up message:

| Stage | Message |
|-------|---------|
| `qualify` | "Olá! Percebo que és ocupado. Tens 2 minutos para continuar a nossa conversa?" |
| `pitch` | "Só a verificar — ficaste com alguma dúvida sobre o que te partilhei?" |
| `objection` | "Ainda estás a pensar? Posso esclarecer alguma coisa específica." |
| default | Generic re-engagement message |

After sending, `increment_followup` is called to update the counter atomically.

---

## 11. Deployment

### Infrastructure

- **Platform:** Fly.io, region `cdg` (Paris — closest to Angola with acceptable latency)
- **Machine:** 1 shared CPU, 512 MB RAM (sufficient for single-worker Uvicorn + LangGraph)
- **Persistent volume:** `lusambu_data` mounted at `/data` for SQLite checkpoint storage
- **Auto-stop:** disabled (`auto_stop_machines = "off"`) to maintain always-on availability
- **Health check:** `GET /health` every 30 seconds

### CI/CD Pipeline

Automatic deployment via GitHub Actions on every push to `main`:

```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

steps:
  - uses: actions/checkout@v4
  - uses: superfly/flyctl-actions/setup-flyctl@master
  - run: flyctl deploy --remote-only
    env:
      FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**Required GitHub Secret:** `FLY_API_TOKEN` — generate with `fly tokens create deploy`.

### Environment Variables (Fly.io Secrets)

Set via `fly secrets set KEY=value`:

```
ANTHROPIC_API_KEY     Claude API key
SUPABASE_URL          Supabase project URL
SUPABASE_KEY          Supabase service role key
EVOLUTION_API_URL     Evolution API base URL (e.g. https://evolution.biscaplus.com)
EVOLUTION_API_KEY     Evolution API authentication key
EVOLUTION_INSTANCE    WhatsApp instance name (e.g. biscaplus)
FIDEL_WHATSAPP_NUMBER Fidel's phone number for escalation notifications
CALENDLY_LINK         Scheduling link sent at closing
OPENAI_API_KEY        OpenAI key (RAG only; leave blank to disable RAG)
DASHBOARD_KEY         Secret key to access the dashboard (optional)
```

### Deployment Constraint — Corporate TLS

`fly deploy --remote-only` uses Fly's Depot builder, which fails behind corporate proxies that perform TLS inspection (x509 certificate error). The workaround is the GitHub Actions pipeline, which runs on GitHub's infrastructure outside the corporate network.

`fly deploy --local-only` requires Docker Desktop accessible via the Windows named pipe (`\\.\pipe\dockerDesktopLinuxEngine`), which may not be available depending on the Docker Desktop configuration.

---

## 12. Configuration Reference

All configuration is loaded via `pydantic-settings` from a `.env` file or environment variables:

```python
# config.py
class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str          # required
    SUPABASE_URL: str               # required
    SUPABASE_KEY: str               # required
    EVOLUTION_API_URL: str          # required
    EVOLUTION_API_KEY: str          # required
    EVOLUTION_INSTANCE: str         # required
    FIDEL_WHATSAPP_NUMBER: str      # required
    CHECKPOINT_DB_PATH: str = "/data/checkpoints.sqlite"
    DASHBOARD_KEY: str = ""         # optional — leave blank to disable auth
    CALENDLY_LINK: str = ""         # optional — falls back to hardcoded URL
    OPENAI_API_KEY: str = ""        # optional — leave blank to disable RAG
```

---

## 13. Local Development

### Prerequisites

```bash
pip install -r requirements.txt
```

### `.env` file

```env
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<service-role-key>
EVOLUTION_API_URL=https://evolution.biscaplus.com
EVOLUTION_API_KEY=<key>
EVOLUTION_INSTANCE=biscaplus
FIDEL_WHATSAPP_NUMBER=<number>
CALENDLY_LINK=https://calendly.com/contact-biscaplus/30min
OPENAI_API_KEY=sk-...   # optional
DASHBOARD_KEY=           # optional
CHECKPOINT_DB_PATH=./checkpoints.sqlite
```

### Interactive Chat (Terminal)

`chat_local.py` provides a local REPL that runs the full agent graph without WhatsApp:

```bash
python chat_local.py
```

Features:
- Loads `.env` via custom parser (bypasses pydantic-settings for local use)
- Disables SSL verification for corporate network compatibility
- Prefixes all LLM responses with `[Lusambu]`
- Uses an in-memory `MemorySaver` (no SQLite needed)
- `quit` or `exit` to stop

### Running the Server Locally

```bash
uvicorn main:app --reload --port 8000
```

### RAG Ingestion

```bash
python ingest.py          # initial ingestion
python ingest.py --reset  # clear and re-ingest (e.g. after content updates)
```

The ingest script includes SSL bypass patches for corporate network environments.

---

## 14. Testing

### Unit Tests

Located in `tests/unit/`. Pure function tests with no I/O, fully deterministic.

**`test_determine_stage.py`** — 17 test cases covering all routing branches:
- Discard when `has_business = False` (takes precedence over everything)
- Escalation triggers: `wants_human`, 2+ objections, max turns, post-Calendly
- Closing sub-stages: missing name/company, data unconfirmed, Calendly unsent
- Pitch, objection, qualify transitions

**`test_closing_data_complete.py`** — 7 test cases:
- Complete with name + company
- `scheduled_time` is not required (handled by Calendly)
- Incomplete with empty strings, `None` values

**`test_extract_lead_info.py`** — tests JSON extraction from sample conversations

**`test_webhook_parser.py`** — tests Evolution API payload parsing

### Integration Tests

Located in `tests/integration/`. Require a live agent graph (uses `MemorySaver`).

**`test_api.py`** — FastAPI endpoint tests via `httpx.AsyncClient`

**`test_graph_discard.py`** — full graph flow for leads without a business

**`test_graph_escalate.py`** — full graph flow for escalation triggers

### Running Tests

```bash
pytest tests/unit/             # fast, no external dependencies
pytest tests/integration/      # requires Anthropic API key
pytest                         # all tests
```

---

## 15. Known Constraints & Design Decisions

### Non-blocking Webhook Handler
Evolution API expects a fast HTTP response. All agent processing runs via `asyncio.create_task()`, returning `{"status":"processing"}` within milliseconds. This prevents Evolution from timing out and retrying (which would cause duplicate messages).

### Double LLM Extraction
`lusambu_node` calls the extractor LLM twice per turn:
1. **Before** generating the response — to know if Calendly should be sent directly
2. **After** generating the response — to capture whether the confirmation summary was just presented

This is intentional: the second extraction with the AI response included allows the next turn to correctly detect `confirms_data`.

### `confirms_data` is Transient
The `confirms_data` field is extracted by the LLM but never stored in Supabase (filtered via `_TRANSIENT_FIELDS`). The database column does not exist. Instead, `data_confirmed` is a persistent boolean in LangGraph state that becomes sticky (`True` once set, never reset).

### Message Offset for Re-entry
When a lead whose conversation ended (`stage = "end"`) sends a new message, the system creates a fresh state with `message_offset = len(old_messages)`. LangGraph appends new messages to the existing thread (preserving checkpoint integrity), but `lusambu_node` slices `messages[offset:]` so the LLM only sees the new conversation.

### A/B Pitch Testing
Variant assignment is random (50/50) and persisted in `LusambuState.prompt_variant` and `lusambu_leads.prompt_variant`. This allows post-hoc analysis of which pitch style converts better by filtering the dashboard by variant.

### Evolution API Webhook Configuration
The webhook is configured per instance via `POST /webhook/set/{instance}`. Key settings:
- `webhookBase64: false` — raw JSON payloads
- `webhookByEvents: false` — single endpoint for all events
- `events: ["MESSAGES_UPSERT"]` — only incoming messages trigger the webhook

**Critical:** The webhook URL must have no leading or trailing whitespace. A single leading space (` https://...`) silently prevents all deliveries.

### RAG Similarity Scores in Portuguese
`text-embedding-3-small` was tested with Portuguese queries against Portuguese content. Similarity scores for relevant matches peaked at ~0.56, making the default threshold of 0.60 too strict. The calibrated threshold is 0.50 based on empirical testing against 3 representative query types.

### SQLite on Fly.io Volume
LangGraph's `AsyncSqliteSaver` is used instead of a managed Redis/PostgreSQL checkpointer for simplicity. The SQLite file lives on a Fly.io persistent volume (`/data/checkpoints.sqlite`). This is appropriate for single-machine deployments. If horizontal scaling is needed in the future, migrate to `langgraph-checkpoint-postgres` with the Supabase PostgreSQL connection.

### Max Turns Limit
The conversation is capped at 12 turns (`MAX_TURNS = 12`). Beyond this, the lead is escalated with the reason "Conversa extensa (N turnos) — revisão humana". This prevents unbounded context growth and ensures very long or unresponsive conversations get human review.

---

*Documentation last updated: May 2026*  
*Maintained by BMST Sistemas e Tecnologias*

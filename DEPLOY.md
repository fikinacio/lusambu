# Deploy — Lusambu no Fly.io

## Arquitectura

```
WhatsApp ──► Evolution API (evolution.biscaplus.com)
                │  webhook POST
                ▼
         Lusambu / FastAPI  (lusambu.fly.dev)
                │
                ├── LangGraph (checkpoints em SQLite /data/checkpoints.sqlite)
                ├── Anthropic Claude (respostas + extracção de leads)
                ├── Supabase (armazenamento de leads)
                └── Evolution API (envio de mensagens + notificação a Fidel)
```

## Pré-requisitos

- Conta no [Fly.io](https://fly.io) com cartão de crédito registado
- `flyctl` instalado (ver abaixo)
- Repositório GitHub: `https://github.com/fikinacio/lusambu`
- Credenciais: Anthropic, Supabase, Evolution API

---

## 1. Instalar o flyctl (Windows)

Abre o PowerShell como Administrador:

```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

Verifica a instalação:

```powershell
fly version
```

---

## 2. Autenticar

```powershell
fly auth login
```

Abre o browser → faz login ou cria conta → aceita.

Confirma:

```powershell
fly auth whoami
```

---

## 3. Criar a app

Na pasta do projecto:

```powershell
cd C:\Users\User\Documents\lusambu
fly apps create lusambu
```

> Se o nome "lusambu" já existir, usa outro (ex: `lusambu-bisca`) e actualiza o campo `app` no `fly.toml`.

---

## 4. Criar o volume persistente

O SQLite que guarda os checkpoints das conversas vive aqui.

```powershell
fly volumes create lusambu_data --region cdg --size 1
```

- `cdg` = Paris (mais próximo de Angola via Europa)
- `--size 1` = 1 GB (suficiente para milhares de conversas)

---

## 5. Definir as variáveis de ambiente (secrets)

```powershell
fly secrets set `
  ANTHROPIC_API_KEY="sk-ant-..." `
  SUPABASE_URL="https://hcwaihggwhjgpmibnhxy.supabase.co" `
  SUPABASE_KEY="eyJ..." `
  EVOLUTION_API_URL="https://evolution.biscaplus.com" `
  EVOLUTION_API_KEY="..." `
  EVOLUTION_INSTANCE="bmst" `
  FIDEL_WHATSAPP_NUMBER="41795748225"
```

> `CHECKPOINT_DB_PATH` já está definido no `fly.toml` como `/data/checkpoints.sqlite` — não precisas de o definir aqui.

---

## 6. Deploy

```powershell
fly deploy
```

Na primeira vez faz build da imagem Docker (~2-3 min). Deploys seguintes são mais rápidos.

URL pública: `https://lusambu.fly.dev`

Verifica:

```powershell
fly status
```

---

## 7. Configurar o webhook na Evolution API

No painel do Evolution (`https://evolution.biscaplus.com`), instância `bmst`:

- **URL do webhook:** `https://lusambu.fly.dev/webhook/lusambu`
- **Evento:** `MESSAGES_UPSERT`

---

## Operações do dia-a-dia

### Ver logs em tempo real

```powershell
fly logs
```

### Ver estado das máquinas

```powershell
fly status
```

### Fazer redeploy após push ao GitHub

```powershell
fly deploy
```

> Fly.io não tem auto-deploy — cada vez que fizeres push ao `main`, tens de correr `fly deploy` manualmente.

### Actualizar um secret

```powershell
fly secrets set NOME_DA_VARIAVEL="novo_valor"
```

Faz redeploy automático após alterar secrets.

### Aceder ao volume (inspecção do SQLite)

```powershell
fly ssh console
ls /data/
```

### Escalar a memória (se necessário)

Edita o `fly.toml`:

```toml
[[vm]]
  memory_mb = 1024
```

Depois `fly deploy`.

---

## Estrutura do fly.toml

```toml
app = "lusambu"
primary_region = "cdg"

[env]
  CHECKPOINT_DB_PATH = "/data/checkpoints.sqlite"

[[mounts]]
  source = "lusambu_data"
  destination = "/data"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "off"
  min_machines_running = 1

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
```

---

## Custos estimados (Fly.io)

| Recurso | Custo |
|---|---|
| 1 VM shared-cpu-1x 512MB | ~$3.19/mês |
| Volume 1 GB | ~$0.15/mês |
| Largura de banda (primeiros 100 GB) | Grátis |
| **Total** | **~$3.34/mês** |

---

## Troubleshooting

### App não arranca

```powershell
fly logs
```

### Webhook não chega

Confirma que o Evolution API tem o URL correcto: `https://lusambu.fly.dev/webhook/lusambu`

### Health check falha

```powershell
fly checks list
```

O endpoint `/health` deve retornar `{"status":"ok","agent":"Lusambu"}`.

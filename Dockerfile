FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependências Python primeiro — melhora cache do Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY config.py main.py ./
COPY agent ./agent
COPY integrations ./integrations
COPY sales_agent ./sales_agent
COPY proposal_agent ./proposal_agent
COPY invoice_agent ./invoice_agent
COPY project_agent ./project_agent

# Volume para persistir os checkpoints SQLite entre redeploys
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# 1 worker — o grafo LangGraph é inicializado uma vez no lifespan.
# FastAPI/async aguenta muita concorrência num único worker.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

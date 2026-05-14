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

EXPOSE 8000

# 1 worker — o grafo LangGraph é inicializado uma vez no lifespan.
# FastAPI/async aguenta muita concorrência num único worker.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

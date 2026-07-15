# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODEL_PATH=/models/qwen3-4b-q4_k_m.gguf \
    LAZY_LOAD_MODEL=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Mount GGUF weights at /models (do not copy into image)
VOLUME ["/models"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

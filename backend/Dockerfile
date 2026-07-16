# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODEL_PATH=/models/qwen3-4b-q4_k_m.gguf \
    LAZY_LOAD_MODEL=true \
    # Portable CPU binary — GGML_NATIVE=ON crashes on VPS with SIGILL (exit 132)
    # when the build host has AVX2/AVX512 the droplet does not.
    CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF" \
    FORCE_CMAKE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install everything except llama-cpp first, then compile llama-cpp portably.
RUN pip install --upgrade pip \
    && grep -v 'llama-cpp-python' requirements.txt > /tmp/req-no-llama.txt \
    && pip install -r /tmp/req-no-llama.txt \
    && pip install --no-cache-dir --force-reinstall --no-binary=llama-cpp-python \
        "llama-cpp-python>=0.3.0,<1.0"

COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

VOLUME ["/models"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

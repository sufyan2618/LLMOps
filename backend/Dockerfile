# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Portable CPU binary — GGML_NATIVE=ON crashes on VPS with SIGILL (exit 132)
    # when the build host has AVX2/AVX512 the droplet does not.
    CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF" \
    FORCE_CMAKE=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Build all Python dependencies in an isolated venv. Compiler headers,
# including linux-libc-dev, remain in this builder stage only.
RUN python -m venv /opt/venv \
    && pip install --upgrade pip \
    && grep -v 'llama-cpp-python' requirements.txt > /tmp/req-no-llama.txt \
    && pip install -r /tmp/req-no-llama.txt \
    && pip install --no-cache-dir --force-reinstall --no-binary=llama-cpp-python \
        "llama-cpp-python>=0.3.0,<1.0"

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODEL_PATH=/models/qwen3-4b-q4_k_m.gguf \
    LAZY_LOAD_MODEL=true \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

# llama.cpp uses the GCC OpenMP runtime, but no compiler or kernel headers
# are needed in production.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

VOLUME ["/models"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

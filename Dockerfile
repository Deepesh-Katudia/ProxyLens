# syntax=docker/dockerfile:1
#
# Default build: the API without the student model (CI, docker compose).
# Cloud Run build (deploy/cloudbuild.yaml):
#   --build-arg INSTALL_STUDENT=1   llama-cpp-python for the fine-tuned GGUF
#   --build-arg BAKE_MODELS=1       BGE + the GGUF baked into the image, so a cold
#                                   start loads from disk instead of downloading 2.4 GB
#   --secret id=hf_token,src=...    the GGUF repo is private; the token is mounted for
#                                   that one RUN step and never stored in a layer
FROM python:3.11-slim AS base

ARG INSTALL_STUDENT=0
ARG BAKE_MODELS=0
ARG EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
ARG STUDENT_GGUF_REPO=deepeshkatudia/proxylens-qwen3b-gguf-v1
ARG STUDENT_GGUF_FILE=proxylens-q4_k_m.gguf

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/app/models/hf \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

WORKDIR /app

# llama.cpp's prebuilt wheel links against OpenMP.
RUN if [ "$INSTALL_STUDENT" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends libgomp1 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Install dependencies first so code changes don't bust the layer cache.
COPY pyproject.toml uv.lock .python-version ./
RUN if [ "$INSTALL_STUDENT" = "1" ]; then EXTRA="--extra student"; else EXTRA=""; fi \
    && uv sync --frozen --no-dev --no-install-project $EXTRA

# The runtime user owns the model cache, so models are downloaded as that user:
# a chown afterwards would copy 2.4 GB into another layer.
RUN useradd --create-home --uid 10001 proxylens && mkdir -p /app/models \
    && chown proxylens /app/models
USER proxylens

# Model files change rarely, so they sit below the code layers.
RUN --mount=type=secret,id=hf_token,required=false,uid=10001 \
    if [ "$BAKE_MODELS" = "1" ]; then \
        HF_TOKEN="$(cat /run/secrets/hf_token 2>/dev/null)" python -c "\
import os, sys; \
from sentence_transformers import SentenceTransformer; \
from huggingface_hub import hf_hub_download; \
SentenceTransformer(sys.argv[1], device='cpu'); \
hf_hub_download(sys.argv[2], sys.argv[3], local_dir='/app/models', token=os.environ.get('HF_TOKEN') or None)" \
        "$EMBEDDING_MODEL" "$STUDENT_GGUF_REPO" "$STUDENT_GGUF_FILE" \
        && rm -rf /app/models/.cache; \
    fi

# Code stays root-owned and read-only for the app user.
COPY app ./app
COPY config ./config

# Cloud Run injects PORT; default to 8000 for local runs.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]

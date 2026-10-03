# ProxyLens

**AI proxy-voting analyst for Indian AGM/EGM resolutions.** Upload a notice, and ProxyLens extracts every resolution, checks it against SEBI LODR and the Companies Act 2013, and recommends FOR / AGAINST / ABSTAIN with cited clauses.

> ⚠️ Research and educational tool. Not investment or voting advice.

**Status:** Phase 0 (scaffold) complete. See [`docs/PROGRESS.md`](docs/PROGRESS.md) and the full build spec in [`SPEC.md`](SPEC.md).

## Stack

FastAPI · pydantic v2 · MongoDB Atlas (Vector Search) · LangGraph · QLoRA fine-tuned Qwen2.5-3B (GGUF) · Gemini on Vertex AI (teacher) · React + Vite + Tailwind · Cloud Run

## Quick start

### Everything in Docker

```bash
cp .env.example .env          # optional: set MONGODB_URI to use Atlas instead of the local container
docker compose up --build
```

| Service | URL |
|---|---|
| API health | http://localhost:8000/healthz |
| API docs | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |
| MongoDB (Atlas Local, has Vector Search) | mongodb://localhost:27017/?directConnection=true |

### Backend without Docker

Requires [uv](https://docs.astral.sh/uv/). The project pins Python 3.11 (`.python-version`).

```bash
uv sync
uv run uvicorn app.main:app --reload
```

> If you have a global `UV_PYTHON` env var set (e.g. `3.12`), it overrides the pin. Run `export UV_PYTHON=3.11` (or `$env:UV_PYTHON="3.11"` in PowerShell) first.

`/healthz` returns `200` only when MongoDB answers a ping. Without `MONGODB_URI` it returns `503` with `"db": "not_configured"`.

### Frontend without Docker

```bash
cd frontend
npm install
npm run dev          # proxies /api to http://localhost:8000
```

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests
uv run pytest
uv run pre-commit install   # ruff + mypy on every commit
```

## Repo layout

```
app/          FastAPI app (api, db, parsing, llm, retrieval, rules, pipeline, schemas)
config/       policy.yaml (house voting policy, Phase 5)
scripts/      corpus build, notice collection, segmentation, labeling
notebooks/    Colab fine-tuning + eval notebooks
eval/         eval harness and results
data/         raw / processed / sft / gold (gitignored)
frontend/     React + Vite + TS + Tailwind
deploy/       GCP deploy scripts
docs/         progress, deploy, design decisions
```

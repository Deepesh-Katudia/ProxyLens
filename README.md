# ProxyLens

**AI proxy-voting analyst for Indian AGM/EGM resolutions.** Upload a notice, and ProxyLens extracts every resolution, checks it against SEBI LODR and the Companies Act 2013, and recommends FOR / AGAINST / ABSTAIN with cited clauses.

> ⚠️ Research and educational tool. Not investment or voting advice.

**Status:** Phases 0–1 complete (regulation corpus + vector search, recall@6 = 1.00 on 20 cases). See [`docs/PROGRESS.md`](docs/PROGRESS.md) and the full build spec in [`SPEC.md`](SPEC.md).

## Stack

FastAPI · pydantic v2 · MongoDB Atlas (Vector Search) · BGE embeddings · LangGraph · QLoRA fine-tuned Qwen2.5-3B (GGUF) · teacher LLM via OpenRouter · React + Vite + Tailwind · Cloud Run

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

## Regulation corpus (RAG)

The corpus is the official consolidated **SEBI LODR 2015** (amended up to 14 July 2026, from sebi.gov.in) plus 17 sections and Schedules IV–V of the **Companies Act 2013**. Both are chunked by legal unit, tagged with the resolution types they govern, embedded with `BAAI/bge-base-en-v1.5`, and stored in Atlas. The build script downloads and caches both PDFs.

> ⚠️ **Companies Act text is pre-amendment.** India Code and MCA were unreachable, so the Act comes from PRS India's copy *as enacted on 29 Aug 2013*. Every Companies Act chunk carries a `notes` warning, and the Act-based rules in `config/policy.yaml` stay `verified: false`. To upgrade, put the amended India Code PDF at `data/raw/regulations/companies_act_2013.pdf` and rebuild. The parser may need small layout tweaks.

```bash
uv run python -m scripts.create_indexes      # Atlas vector + text indexes (once)
uv run python -m scripts.build_corpus        # parse, embed, upsert (--dry-run to skip the DB)
uv run python -m scripts.eval_retrieval      # recall@6 on tests/retrieval_cases.yaml
```

Try it: `GET /api/v1/regulations/search?q=material related party transaction threshold&type=RELATED_PARTY_TRANSACTION`

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests scripts
uv run pytest                                  # unit tests
RUN_ATLAS_TESTS=1 uv run pytest tests/test_retrieval_atlas.py   # live recall@6 check
uv run pre-commit install   # ruff + mypy on every commit
```

## Repo layout

```
app/          FastAPI app (api, corpus, db, parsing, llm, retrieval, rules, pipeline, schemas)
config/       policy.yaml (verified rules), corpus_tags.yaml (applies_to map)
scripts/      corpus build, notice collection, segmentation, labeling
notebooks/    Colab fine-tuning + eval notebooks
eval/         eval harness and results
data/         raw / processed / sft / gold (gitignored)
frontend/     React + Vite + TS + Tailwind
deploy/       GCP deploy scripts
docs/         progress, deploy, design decisions
```

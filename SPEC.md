# ProxyLens — AI Proxy-Voting Analyst for Indian AGM Resolutions

> Build spec for Claude Code. Put this file in the repo root as `SPEC.md`.
> Owner: Deepesh · Target role: AI Engineer (NLP/ML, LLMs, fine-tuning, vector DBs, GCP)

---

## 0. Instructions for Claude Code

- Work **phase by phase** (Section 10). Do not start a phase until the previous phase's acceptance criteria pass.
- At the end of each phase: run tests, update `README.md` and `docs/PROGRESS.md`, and stop for review.
- Ask before adding a dependency that is not listed in Section 4.
- Never commit secrets. All config goes through `.env` / `pydantic-settings`. Ship a `.env.example`.
- Prefer small, typed, tested modules. Use Python 3.11 with type hints everywhere, `ruff` + `mypy` clean.
- GPU work (fine-tuning) does **not** run in this repo's runtime. Generate Colab notebooks for it (Section 7).
- Regulation details in Section 6 must be checked against the current SEBI/MCA text during Phase 1. Rules change. Store the source URL and the "as-of" date with every rule.

---

## 1. Problem & pitch

Indian listed companies put resolutions to shareholders at every AGM/EGM: director appointments, pay hikes, related-party transactions (RPTs), auditor changes, and capital raises. Institutional investors must vote on thousands of these each season. Proxy advisory firms (e.g. IiAS, InGovern, SES) employ analysts who read each notice, check it against SEBI LODR and the Companies Act 2013, and publish FOR/AGAINST/ABSTAIN recommendations.

**ProxyLens automates the first pass:**

1. Upload an AGM/EGM notice PDF (or give a BSE scrip code).
2. Extract every resolution into structured JSON (type, people, amounts, tenure, special vs ordinary).
3. Retrieve the governing regulations from MongoDB Atlas Vector Search.
4. Run deterministic rule checks plus an LLM reasoning step.
5. Output a recommendation per resolution with **cited clauses**, a confidence score, and flags for a human analyst.

**The ML story recruiters should see:**

> "A QLoRA fine-tuned 3B model, distilled from a frontier teacher, extracts and classifies resolutions at ~X% of the teacher's accuracy for ~1/Y of the cost. It is served on GCP Cloud Run with RAG over Atlas Vector Search, and an analyst feedback loop feeds the next training round."

Fill in X and Y from real eval numbers (Section 8). Never invent them.

**Disclaimer (show in UI and README):** Research and educational tool. Not investment or voting advice.

---

## 2. Scope

### In scope (MVP)
- PDF ingestion of AGM/EGM notices (English, text-based PDFs; OCR fallback is a stretch goal).
- Regulation corpus: SEBI LODR 2015 (consolidated), Companies Act 2013 (selected sections), plus a configurable house voting policy.
- Resolution extraction + classification (fine-tuned small model, with a teacher fallback).
- RAG over regulations with citations.
- Hybrid decision engine: rules engine + LLM reasoning.
- FastAPI backend, React frontend, MongoDB Atlas, Cloud Run deployment.
- Eval harness + dashboard comparing base vs fine-tuned vs teacher.
- Analyst feedback capture (override + reason) stored for retraining.

### Out of scope (MVP)
- Scanned/handwritten PDFs, Hindi notices, real-time BSE scraping at scale, auth beyond a simple API key, multi-tenant.

---

## 3. Architecture

```
                ┌──────────────┐
  PDF upload ──▶│  FastAPI API │──▶ jobs collection (status: queued→done)
                └──────┬───────┘
                       ▼
            ┌─────────────────────┐
            │ 1. Parse & segment  │  pymupdf → page text → resolution splitter
            └─────────┬───────────┘
                      ▼
            ┌─────────────────────┐
            │ 2. Extract/classify │  Fine-tuned Qwen2.5-3B (GGUF, llama.cpp)
            │    (structured JSON)│  fallback → teacher (Gemini on Vertex AI)
            └─────────┬───────────┘
                      ▼
            ┌─────────────────────┐
            │ 3. Retrieve rules   │  Atlas $vectorSearch (+ optional $search hybrid)
            │                     │  filtered by resolution_type
            └─────────┬───────────┘
                      ▼
            ┌─────────────────────┐
            │ 4. Decide           │  rules engine (deterministic checks, policy.yaml)
            │                     │  + LLM reasoner (LangGraph node) → recommendation
            └─────────┬───────────┘
                      ▼
            ┌─────────────────────┐
            │ 5. Persist + serve  │  analyses collection → React UI
            └─────────┬───────────┘
                      ▼
               Analyst override ──▶ feedback collection ──▶ next fine-tune dataset
```

Orchestration: **LangGraph** state machine (`parse → extract → validate → retrieve → rule_check → reason → assemble`). Each node is a pure function over a typed state object, so each node can be tested on its own.

**Model provider abstraction** (`app/llm/providers.py`): one interface `generate_json(prompt, schema) -> dict` with implementations:
- `LocalGGUFProvider`: llama-cpp-python, loads the fine-tuned GGUF.
- `VertexGeminiProvider`: teacher and fallback (model name from config).
- `BaseHFProvider`: base model, used only for eval runs.

The provider is chosen per task by config, so the eval harness can swap them.

---

## 4. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11 (backend/ML), TypeScript (frontend) |
| API | FastAPI, Uvicorn, pydantic v2, pydantic-settings |
| Orchestration | LangChain core + LangGraph |
| PDF | PyMuPDF (`pymupdf`); stretch: `pytesseract` OCR |
| DB / Vector | MongoDB Atlas (user's sandbox cluster), Atlas Vector Search, `pymongo` (async via `motor`) |
| Embeddings | Default `BAAI/bge-base-en-v1.5` (768-d, sentence-transformers, free). Option: Vertex AI text embeddings (configurable) |
| Teacher LLM | Gemini via Vertex AI (`google-cloud-aiplatform` / `google-genai`); model name in config |
| Student model | `Qwen/Qwen2.5-3B-Instruct` (alternative: `meta-llama/Llama-3.2-3B-Instruct`) |
| Fine-tuning | Unsloth + TRL `SFTTrainer`, QLoRA 4-bit, on Colab/Kaggle T4 |
| Serving student | GGUF Q4_K_M via `llama-cpp-python` on Cloud Run (CPU, 4 vCPU / 8 GiB) |
| Model registry | Hugging Face Hub (private repo) for LoRA adapter + GGUF |
| Frontend | React + Vite + TypeScript + Tailwind |
| Deploy | Docker → Artifact Registry → Cloud Run (api) ; frontend on Cloud Run or Firebase Hosting |
| Secrets | GCP Secret Manager |
| CI | GitHub Actions: ruff, mypy, pytest, docker build |
| Eval tracking | JSON results in `eval/results/` + MongoDB `eval_runs` collection; optional Weights & Biases |
| Testing | pytest, pytest-asyncio, `mongomock-motor` for unit tests |

---

## 5. Data model (MongoDB)

Database: `proxylens`

### `regulations` (the RAG corpus)
```json
{
  "_id": "lodr_reg23_4",
  "source": "SEBI_LODR_2015",            // SEBI_LODR_2015 | COMPANIES_ACT_2013 | HOUSE_POLICY
  "citation": "Regulation 23(4), SEBI LODR 2015",
  "section_path": ["Chapter IV", "Regulation 23", "(4)"],
  "text": "...chunk text...",
  "applies_to": ["RELATED_PARTY_TRANSACTION"],   // resolution types this chunk is relevant to
  "source_url": "https://www.sebi.gov.in/...",
  "as_of": "2026-10-01",
  "embedding": [/* 768 floats */]
}
```

Atlas Vector Search index `regulations_vec`:
```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 768, "similarity": "cosine" },
    { "type": "filter", "path": "applies_to" },
    { "type": "filter", "path": "source" }
  ]
}
```
Optional Atlas Search (full-text) index `regulations_text` on `text` + `citation`, for hybrid retrieval.

Chunking: split **by legal unit** (regulation / sub-regulation / proviso), not fixed tokens. Keep the parent citation in every chunk. Max ~400 tokens. If a unit is longer, split it with overlap and keep the same citation.

### `documents`
```json
{ "_id": ObjectId, "company": "XYZ Ltd", "bse_code": "500325", "meeting_type": "AGM",
  "meeting_date": "2026-08-28", "fiscal_year": "FY26", "file_sha256": "...",
  "pages": 42, "source_url": "...", "uploaded_at": ISODate }
```

### `resolutions`
```json
{
  "_id": ObjectId, "document_id": ObjectId, "item_no": 4,
  "raw_text": "...", "explanatory_statement": "...",
  "extracted": { /* ResolutionExtraction, see 5.1 */ },
  "extractor": { "provider": "local_gguf", "model": "proxylens-qwen3b-v1", "latency_ms": 2100 }
}
```

### `analyses`
```json
{
  "_id": ObjectId, "resolution_id": ObjectId,
  "recommendation": "FOR | AGAINST | ABSTAIN | NEEDS_REVIEW",
  "confidence": 0.82,
  "rule_findings": [ { "rule_id": "ID_TENURE_MAX", "status": "FAIL|PASS|NA", "detail": "...", "citation": "Sec 149(10)/(11), Companies Act 2013" } ],
  "rationale": "2–5 sentence explanation",
  "citations": [ { "regulation_id": "lodr_reg23_4", "quote": "short supporting span" } ],
  "retrieved_ids": ["..."], "pipeline_version": "0.3.0", "created_at": ISODate
}
```

### `feedback`
```json
{ "analysis_id": ObjectId, "analyst_recommendation": "AGAINST", "reason": "...",
  "corrected_extraction": { /* optional */ }, "created_at": ISODate }
```

### `eval_runs`
```json
{ "run_id": "2026-10-15_ft-v1", "provider": "local_gguf", "model": "...", "split": "test",
  "metrics": { ... }, "per_item": [ ... ], "created_at": ISODate }
```

### 5.1 `ResolutionExtraction` schema (pydantic; also the fine-tune target format)
```python
class ResolutionType(str, Enum):
    ADOPT_FINANCIALS = "ADOPT_FINANCIALS"
    DIVIDEND = "DIVIDEND"
    DIRECTOR_REAPPOINT_ROTATION = "DIRECTOR_REAPPOINT_ROTATION"
    INDEPENDENT_DIRECTOR_APPOINT = "INDEPENDENT_DIRECTOR_APPOINT"
    NON_INDEPENDENT_DIRECTOR_APPOINT = "NON_INDEPENDENT_DIRECTOR_APPOINT"
    MANAGERIAL_REMUNERATION = "MANAGERIAL_REMUNERATION"
    RELATED_PARTY_TRANSACTION = "RELATED_PARTY_TRANSACTION"
    AUDITOR_APPOINT = "AUDITOR_APPOINT"
    AUDITOR_REMUNERATION_COST = "AUDITOR_REMUNERATION_COST"  # cost auditor ratification
    ESOP = "ESOP"
    CAPITAL_RAISE = "CAPITAL_RAISE"  # QIP, preferential, NCDs
    BORROWING_LIMITS = "BORROWING_LIMITS"  # Sec 180
    ARTICLES_OR_MOA_AMENDMENT = "ARTICLES_OR_MOA_AMENDMENT"
    OTHER = "OTHER"


class Person(BaseModel):
    name: str
    role: str | None  # e.g. "Independent Director", "Managing Director"
    age: int | None
    din: str | None
    is_promoter: bool | None
    tenure_years_proposed: float | None
    prior_tenure_years: float | None
    board_attendance_pct: float | None


class Money(BaseModel):
    amount_inr: float | None  # normalized to INR (crore/lakh → INR)
    raw: str  # as written


class ResolutionExtraction(BaseModel):
    item_no: int
    title: str
    resolution_type: ResolutionType
    is_special_resolution: bool
    persons: list[Person] = []
    amounts: list[Money] = []
    counterparty: str | None  # RPTs
    counterparty_is_related: bool | None
    transaction_nature: str | None  # RPTs: "sale of goods", "loan", ...
    duration_years: float | None
    key_facts: list[str]  # <= 5 short factual bullets
```

The student model must output **only** this JSON. Validate with pydantic. On failure: one repair retry, then fall back to the teacher. Log the fallback rate; it's a metric.

---

## 6. Decision engine

### 6.1 Rules engine (`app/rules/`)
Deterministic checks declared in `config/policy.yaml`. Each rule has: `id`, `applies_to`, `kind` (`LAW` or `POLICY`), `check` (a Python function name), `params`, `citation`, `source_url`, `as_of`.

`LAW` = statutory/regulatory requirement. `POLICY` = house voting guideline (configurable, opinionated). The UI must show which is which.

Starter rules. **Verify each against the current official text in Phase 1 and fix params/citations if they differ:**

| id | applies_to | kind | Check (summary) | Citation to verify |
|---|---|---|---|---|
| `ID_TENURE_MAX` | INDEPENDENT_DIRECTOR_APPOINT | LAW | Prior + proposed tenure must not exceed two consecutive terms of up to 5 years each | Companies Act 2013 s.149(10)–(11) |
| `ID_SECOND_TERM_SPECIAL` | INDEPENDENT_DIRECTOR_APPOINT | LAW | Re-appointment for a second term needs a special resolution | s.149(10) |
| `NED_AGE_75_SPECIAL` | *_DIRECTOR_* | LAW | Non-executive director aged 75+ needs a special resolution | SEBI LODR Reg 17(1A) |
| `DIRECTOR_PERIODIC_APPROVAL` | *_DIRECTOR_* | LAW | Directors' continuation needs shareholder approval at least once every 5 years | SEBI LODR Reg 17(1D) |
| `RPT_MATERIAL_APPROVAL` | RELATED_PARTY_TRANSACTION | LAW | Material RPT needs prior shareholder approval; related parties must not vote in favour | SEBI LODR Reg 23(4); materiality threshold in Reg 23(1) |
| `EXEC_PROMOTER_PAY_SPECIAL` | MANAGERIAL_REMUNERATION | LAW | Executive promoter-director pay above the Reg 17(6)(e) threshold needs a special resolution | SEBI LODR Reg 17(6)(e) |
| `AUDITOR_ROTATION` | AUDITOR_APPOINT | LAW | Audit firm: max two terms of 5 consecutive years | Companies Act s.139(2) |
| `POL_ATTENDANCE_MIN` | *_DIRECTOR_* | POLICY | Vote AGAINST if board attendance < 75% over the last 3 years (configurable) | House policy |
| `POL_PAY_JUMP` | MANAGERIAL_REMUNERATION | POLICY | Flag if proposed pay rises > 50% YoY or has no cap | House policy |
| `POL_RPT_NO_CAP` | RELATED_PARTY_TRANSACTION | POLICY | Flag if the omnibus RPT has no monetary cap or tenure > 5 years | House policy |

A rule returns `PASS | FAIL | NA | INSUFFICIENT_DATA`. `INSUFFICIENT_DATA` must never be treated as a pass.

### 6.2 LLM reasoner
Inputs: extraction JSON, rule findings, top-k retrieved regulation chunks (k=6, filtered by `applies_to`), and `policy.yaml` excerpts.
Output (pydantic-validated):
```json
{ "recommendation": "FOR|AGAINST|ABSTAIN|NEEDS_REVIEW", "confidence": 0.0-1.0,
  "rationale": "...", "citations": [{"regulation_id": "...", "quote": "..."}] }
```
Hard constraints, enforced in code after generation:
- Any `LAW` rule = `FAIL` → recommendation cannot be `FOR`.
- Every citation's `regulation_id` must be in `retrieved_ids`, and its `quote` must be a substring of that chunk. Drop invalid citations and lower confidence.
- `confidence < 0.6` or any `INSUFFICIENT_DATA` on a LAW rule → `NEEDS_REVIEW`.

The reasoner uses the teacher model by default. Fine-tuning the reasoner is a stretch goal (Section 7.5).

---

## 7. Fine-tuning plan (the centerpiece)

### 7.1 What we fine-tune
Task: **AGM resolution → `ResolutionExtraction` JSON** (classification + structured extraction).
Why this task: it's high-volume, well-defined, easy to score automatically, and the place where a small model can realistically match a frontier model.

### 7.2 Data pipeline (`data/`, `scripts/`)
1. **Collect notices**: `scripts/collect_notices.py`. Target 150–250 AGM/EGM notices from NIFTY 500 companies, FY23–FY26, across sectors. Source: BSE/NSE corporate announcements (public PDFs). Be polite: rate-limit, set a proper User-Agent, cache downloads, and respect robots.txt and the sites' terms. Also support a manual mode: Deepesh drops PDFs into `data/raw/notices/`, and a `manifest.csv` records company, date and URL.
2. **Segment**: `scripts/segment.py`. Split each notice into items (resolution text + its explanatory statement under Sec 102). Expect ~8–15 items per notice, so ~2,000–3,000 resolutions in total.
3. **Teacher labeling**: `scripts/teacher_label.py`. Gemini (Vertex) produces `ResolutionExtraction` JSON with a strict schema prompt. Keep the raw teacher output, validation status and token cost.
4. **Quality filter**: drop items whose JSON fails validation, and spot-check flagged disagreements. If a second teacher pass is run, keep only items where both passes agree on `resolution_type`.
5. **Gold set (human)**: Deepesh hand-labels **150 resolutions** in a simple labeling UI (`frontend/` route `/label`, or a Streamlit script `scripts/label_ui.py`). This is the test set. It is **never** teacher-labeled and never used in training.
6. **Split by company** (avoid leakage): train 80% / val 10% of the teacher-labeled set, grouped by company. The gold test set comes from companies that appear in neither train nor val.
7. Export to `data/sft/{train,val}.jsonl` in chat format:
   ```json
   {"messages":[{"role":"system","content":"<extraction system prompt>"},
                {"role":"user","content":"<resolution + explanatory statement>"},
                {"role":"assistant","content":"<ResolutionExtraction JSON>"}]}
   ```
8. Dataset card: `data/DATASET_CARD.md` (sources, counts per type, class balance, known biases, license notes).

### 7.3 Training (Colab/Kaggle T4): `notebooks/01_finetune_qlora.ipynb`
- Unsloth `FastLanguageModel.from_pretrained("unsloth/Qwen2.5-3B-Instruct-bnb-4bit", max_seq_length=4096, load_in_4bit=True)`.
- LoRA: r=16, alpha=16, dropout=0, target modules q,k,v,o,gate,up,down.
- TRL `SFTTrainer`: train on assistant tokens only (`train_on_responses_only`), lr 2e-4, cosine schedule, 2–3 epochs, effective batch 16 (bs=2 × grad_accum=8), fp16 on T4, seed 3407.
- Log train/val loss, plus val-set JSON validity and type accuracy every epoch.
- Save: LoRA adapter → HF Hub (private) `deepesh/proxylens-qwen3b-lora-v1`; merged GGUF `Q4_K_M` → HF Hub `deepesh/proxylens-qwen3b-gguf-v1`.
- The notebook must run top-to-bottom on a free T4 within session limits. Use checkpointing so it can resume.

### 7.4 Notebook set
- `01_finetune_qlora.ipynb`: train + export.
- `02_eval_student.ipynb`: runs base and fine-tuned on the gold test set on GPU, then writes `eval/results/*.json` in the same format the repo's eval harness reads.
- `README` cell at the top of each: what it does, runtime, and the inputs/outputs it expects.

### 7.5 Stretch
- v2 training round that adds `feedback` collection corrections (show the before/after metric delta; this is the "continuous optimisation" story).
- Fine-tune a reasoner on teacher rationales (distillation), evaluated on recommendation agreement with the gold set.
- Fine-tune the embedding model on (resolution, relevant-regulation) pairs, evaluated on retrieval recall@k.

---

## 8. Evaluation (`eval/`)

`python -m eval.run --provider {base,finetuned,teacher} --split test` writes results to `eval/results/` and `eval_runs`.

| Metric | Definition |
|---|---|
| JSON validity rate | % outputs that parse and validate against `ResolutionExtraction` (before repair) |
| Type accuracy / macro-F1 | `resolution_type` vs gold, with a confusion matrix |
| Field-level F1 | For persons (name match), amounts (±1%), `is_special_resolution`, counterparty |
| Recommendation agreement | End-to-end pipeline recommendation vs Deepesh's gold label (if labeled) |
| Citation precision | % of citations that pass the substring + retrieved-id check |
| Retrieval recall@6 | Gold "should-cite" regulation in top-6 (needs ~50 annotated items) |
| Fallback rate | % items where the student failed and the teacher was used |
| Latency p50/p95 | Per resolution, on the deployed Cloud Run config |
| Cost per 1k resolutions | Teacher: real token usage × price. Student: Cloud Run CPU-seconds × price |

Deliverable: `eval/REPORT.md`, auto-generated, with a table comparing base 3B, fine-tuned 3B and teacher, a confusion matrix PNG, and 5 annotated failure cases. The frontend `/eval` page renders the latest run.

Write a `pytest` regression test that fails if the fine-tuned model's validity rate or type macro-F1 drops more than 2 points below the stored baseline (runs only when the model file is present).

---

## 9. API & frontend

### API (FastAPI, `/api/v1`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/documents` | Upload PDF (multipart) → `{document_id, job_id}` |
| GET | `/jobs/{id}` | Status: queued / parsing / extracting / analysing / done / failed, plus progress |
| GET | `/documents/{id}` | Document metadata + resolutions + analyses |
| GET | `/resolutions/{id}` | One resolution with extraction, rule findings, citations |
| POST | `/analyses/{id}/feedback` | Analyst override |
| GET | `/regulations/search?q=&type=` | Debug RAG: returns top-k chunks with scores |
| GET | `/eval/latest` | Latest eval run summary |
| GET | `/healthz` | Liveness (DB ping, model loaded) |

Background processing: FastAPI `BackgroundTasks` for MVP. Document how you'd move to Cloud Tasks / Pub/Sub; don't build it.
Auth: `X-API-Key` header for write endpoints (key in Secret Manager).

### Frontend (React + Vite + TS + Tailwind)
- **Upload page**: drag-drop PDF with a live job progress bar.
- **Report page**: company header; a table of resolutions (item #, title, type chip, recommendation badge, confidence). Click a row to open a drawer with extracted fields, rule findings (LAW vs POLICY, PASS/FAIL), rationale, and citations (hover shows the quote; click opens the regulation chunk). An "Override" button opens the feedback form.
- **Eval page**: the model comparison table + confusion matrix + cost/latency chart.
- **About page**: architecture diagram, disclaimer, links to the GitHub repo and HF models.
- Keep it clean and fast. This is what the interviewer clicks first.

---

## 10. Phases & acceptance criteria

### Phase 0: Scaffold
- Repo layout (Section 11), `pyproject.toml` (uv or poetry), pre-commit (ruff, mypy), Dockerfile, docker-compose (api + frontend), GitHub Actions CI, `.env.example`, `config.py` (pydantic-settings), `/healthz`.
- ✅ `docker compose up` serves `/healthz` → 200 with DB connectivity; CI green.

### Phase 1: Regulation corpus + vector search
- `scripts/build_corpus.py`: download/parse the LODR consolidated PDF and the chosen Companies Act sections (149, 152, 160, 177, 178, 180, 188, 196, 197, 139, 102 + Schedule IV, Schedule V). Chunk by legal unit, tag `applies_to`, embed, and upsert into `regulations`.
- `scripts/create_indexes.py`: creates the Atlas vector (and optional text) index via the driver's `create_search_index`.
- `app/retrieval/`: `retrieve(query, resolution_type, k)` using `$vectorSearch` with a filter. Optional hybrid via reciprocal-rank fusion with `$search`.
- Verify the Section 6.1 rule params/citations against the official text and record `source_url` + `as_of`.
- ✅ 20 hand-written queries in `tests/retrieval_cases.yaml`, with recall@6 ≥ 0.8; the `/regulations/search` endpoint works.

### Phase 2: PDF parsing + segmentation
- `app/parsing/`: PyMuPDF text extraction, header/footer stripping, item splitter (regex on "Item No." / "Resolution No." / numbered SPECIAL BUSINESS headings), and explanatory statement alignment.
- ✅ On 10 sample notices in `tests/fixtures/`, segmentation matches the hand-counted item counts on ≥ 9 of 10; unit tests cover the edge cases.

### Phase 3: Teacher pipeline + data collection
- `VertexGeminiProvider`, an extraction prompt, schema validation + repair, cost logging.
- `scripts/collect_notices.py`, `segment.py`, `teacher_label.py`, `make_sft.py`, the labeling UI, and `DATASET_CARD.md`.
- ✅ ≥ 1,500 validated teacher-labeled resolutions; company-grouped splits; labeling UI usable for the 150 gold items.

### Phase 4: Fine-tuning notebooks
- `notebooks/01_finetune_qlora.ipynb`, `02_eval_student.ipynb` (Section 7).
- `LocalGGUFProvider` loads the model from the HF Hub (cached) or a local path.
- ✅ Deepesh runs the notebook on Colab; the GGUF loads locally and returns valid JSON on 10 smoke-test items.

### Phase 5: Decision engine + LangGraph pipeline
- `config/policy.yaml`, rule functions, LLM reasoner, post-generation constraint enforcement (Section 6.2), and the LangGraph graph wiring all nodes.
- ✅ Unit tests for every rule (pass/fail/NA/insufficient); integration test runs a full notice end-to-end with mocked LLMs; constraint violations are impossible by test.

### Phase 6: API + frontend
- All Section 9 endpoints and pages.
- ✅ Upload a real notice locally and see the full report with citations within ~2 minutes; the override saves to `feedback`.

### Phase 7: Eval harness + report
- `eval/run.py`, metrics, `REPORT.md` generator, `/eval` page, regression test.
- ✅ The report shows base vs fine-tuned vs teacher on the gold set with real numbers.

### Phase 8: Deploy to GCP
- Artifact Registry + Cloud Run (api: 4 vCPU / 8 GiB, min-instances 0, concurrency 2; model baked into the image or pulled at startup from HF/GCS), Secret Manager (Mongo URI, API key, HF token), and a Vertex AI service account with least privilege. Frontend on Cloud Run or Firebase Hosting. Atlas network access configured for Cloud Run egress.
- `deploy/` scripts + `docs/DEPLOY.md` (exact `gcloud` commands), and GitHub Actions deploy on tag.
- Structured JSON logging; a request ID through every pipeline node; per-node latency logged.
- ✅ Public URL works end-to-end; cold start documented; `README` has the live link.

### Phase 9: Polish for recruiters
- README: one-line pitch, 60-second GIF demo, architecture diagram, eval table, cost table, "What I'd do next", and the disclaimer.
- `docs/DESIGN_DECISIONS.md`: why distillation, why a 3B model, why rules + LLM hybrid, why chunk by legal unit, and the tradeoffs.
- Model card on the HF Hub.
- ✅ A stranger can understand the project in 2 minutes from the README.

---

## 11. Repo layout

```
proxylens/
├── SPEC.md
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── config/
│   └── policy.yaml
├── app/
│   ├── main.py                 # FastAPI app factory
│   ├── config.py
│   ├── api/                    # routers
│   ├── db/                     # motor client, collections, index helpers
│   ├── parsing/                # pdf → items
│   ├── llm/                    # providers, prompts, json repair
│   ├── retrieval/              # embeddings, vectorSearch, hybrid
│   ├── rules/                  # rule engine + rule functions
│   ├── pipeline/               # LangGraph graph + nodes + state
│   └── schemas/                # pydantic models (ResolutionExtraction, etc.)
├── scripts/                    # corpus build, collect, segment, label, make_sft
├── notebooks/                  # 01_finetune_qlora, 02_eval_student
├── eval/                       # run.py, metrics.py, report.py, results/
├── data/                       # raw/, processed/, sft/, gold/ (gitignored except cards/manifests)
├── frontend/                   # React + Vite + TS + Tailwind
├── deploy/                     # gcloud scripts, cloudbuild.yaml
├── tests/
└── docs/                       # PROGRESS.md, DEPLOY.md, DESIGN_DECISIONS.md, architecture.png
```

---

## 12. Config (`.env.example`)

```
MONGODB_URI=
MONGODB_DB=proxylens
EMBEDDING_PROVIDER=local            # local | vertex
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
EMBEDDING_DIM=768
GCP_PROJECT_ID=
GCP_REGION=asia-south1
TEACHER_MODEL=                      # Gemini model id on Vertex AI
STUDENT_PROVIDER=local_gguf         # local_gguf | vertex | base_hf
STUDENT_GGUF_REPO=deepesh/proxylens-qwen3b-gguf-v1
STUDENT_GGUF_FILE=proxylens-q4_k_m.gguf
HF_TOKEN=
API_KEY=
LOG_LEVEL=INFO
```

---

## 13. Manual steps for Deepesh (Claude Code can't do these)

1. Atlas: get the sandbox cluster connection string and allow network access (your IP + Cloud Run egress later). Confirm Vector Search is available on the tier.
2. GCP: create a project, enable Vertex AI, Cloud Run, Artifact Registry and Secret Manager, set up billing alerts, and create a service account.
3. Hugging Face: create an account + write token; create the private model repos.
4. Run the notebooks on Colab/Kaggle (T4) and push the artifacts to the HF Hub.
5. Hand-label the 150 gold resolutions (~4–6 hours). This is what makes the eval credible.
6. Record the demo GIF and write the LinkedIn post.

---

## 14. Definition of done

- Live URL; upload a real AGM notice and get a cited per-resolution report.
- Fine-tuned 3B model on the HF Hub with a model card.
- `eval/REPORT.md` with real base vs fine-tuned vs teacher numbers, cost and latency.
- CI green, tests for rules/parsing/retrieval/pipeline, one-command local run.
- README a recruiter can scan in 2 minutes.

# Progress

## Phase 7: Eval harness + report (built 2026-10-05; awaiting review)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| `eval/run.py`, metrics, `REPORT.md` generator, `/eval` page, regression test | ✅ `eval/run.py` (teacher / any OpenRouter model / local GGUF; resumable), `eval/metrics.py`, `eval/report.py` (REPORT.md, SVG confusion matrices, `eval_runs` summary), `/eval` page (comparison table, confusion matrix per model, latency and cost bars, reference banner), `tests/test_eval_regression.py` + `eval/baseline.json` |
| The report shows base vs fine-tuned vs teacher **on the gold set** with real numbers | ⚠️ Partly. Real numbers for the teacher (184 items), the base 3B (184, Colab T4), the fine-tuned GGUF (first 30 items) and an extra untuned 7B baseline (184). **Fine-tuned on all 184 still needs the notebook's fine-tuned run** (Deepesh). The set is **not human gold**: see below |

### Reference labels: what they really are
Plan: a model drafts, Deepesh reviews. `scripts/draft_gold.py` drafted all 184 items with Claude Sonnet 5.5 ($1.81; a different model family from the Gemini teacher). The labels file shows all 184 saved within 3 minutes, a median 0.8 s apart, and 183 identical to their drafts. So they were not reviewed. The report does not assert provenance; it derives it from the files (`eval/reference.py`): **"Mixed reference: 1 human-labelled, 183 model drafts saved unchanged."** That sentence is printed above every table, and the /eval page shows it as a banner. Reviewing the items on /label (each save records `draft_model`) upgrades the claim automatically.

### Results (2026-10-05)
| Model | n | JSON valid | Type acc. | Type macro-F1 | Fallback | Latency p50 | Cost / 1k |
|---|---|---|---|---|---|---|---|
| Teacher (Gemini 3.8 Flash) | 184 | 100.0% | 94.6% | 91.0% | 0.0% | 2.8 s | $2.74 |
| Fine-tuned 3B (GGUF Q4_K_M, laptop CPU, JSON grammar) | 30 | 100.0% | 96.7% | 90.9% | 0.0% | 41.6 s | $4.82 (estimate) |
| Base Qwen2.5-3B, zero-shot (Colab T4) | 184 | 47.8% | 36.4% | 48.8% | — | 15.8 s | — |
| Untuned Qwen2.5-7B | 184 | 26.1% | 24.5% | 31.1% | 34.2% | 5.0 s | $0.31 |

- The fine-tuned 3B matches the teacher on type macro-F1 over its 30 items. The one miss: a whole-time director's re-appointment *with pay terms*, labelled MANAGERIAL_REMUNERATION by the reference.
- **Honest cost finding:** at laptop-CPU latency (p50 41.6 s), the student costs *more* per 1,000 resolutions on Cloud Run ($4.82, estimated) than the teacher API ($2.74). The "fraction of the teacher's cost" story only holds if Phase 8 gets serving latency down (more vCPUs, smaller context, batching) or if API prices rise. Phase 8 measures real Cloud Run latency.
- **What fine-tuning buys at 3B:** the same model untuned gets 47.8% JSON validity and 48.8% type macro-F1 zero-shot, against 100% and 90.9% fine-tuned (30-item subset; the full-184 fine-tuned run is pending). An untuned 7B does worse still (26.1% valid).
- Citation precision before guardrails: 100% (5/5), but over only 6 web-app analyses. Too few to mean much.
- Recommendation agreement: not measured (no vote labels).

### Design notes
- JSON validity is measured on the first reply; invalid replies count as wrong in every other metric and appear as `INVALID` in the confusion matrix. Fallback rate is measured only where a repair was attempted (`eval.run`); notebook runs show —.
- Grammar-constrained decoding makes JSON validity about 100% by construction, so such rows are labelled "JSON grammar".
- F1 shows — when the items contain nothing of that kind (e.g. no counterparties in the 30-item subset), not 0%. Rows on different item counts are flagged.
- Persons match on names with honorifics and punctuation removed; amounts match one-to-one within ±1%; counterparty matches on containment after dropping "Private Limited", etc.
- The confusion matrix is SVG written directly (no plotting dependency) and renders on GitHub.
- The regression test is opt-in (`PROXYLENS_MODEL_TESTS=1`, about 30 min on CPU). It re-runs the GGUF on the 30 baseline items and fails on a drop of more than 2 points in JSON validity or type macro-F1.
- CI now type-checks `eval/` too.

### Next (Deepesh)
1. Base 3B run done (`eval/results/2026-10-05_base_hf_test.json`). Still to do: the fine-tuned run from `notebooks/02_eval_student.ipynb` on all 184 items; copy its JSON into `eval/results/`; run `uv run python -m eval.report --db`.
2. Optional, to turn the reference into real gold: review items on /label.


## Phase 6: API + frontend (built 2026-10-04; accepted)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| All SPEC 9 endpoints and pages | ✅ `POST /documents`, `GET /jobs/{id}`, `GET /documents/{id}` (plus a list), `GET /resolutions/{id}`, `POST /analyses/{id}/feedback`, `GET /regulations/search` + `/regulations/{id}`, `GET /eval/latest`, `/healthz` (now reports whether the model is loaded). Pages: Analyse (upload with live progress), Report (table + drawer), Evaluation (empty state until Phase 7), About, Gold labels |
| Upload a real notice locally and see the full report with citations within ~2 minutes | ✅ 2026-10-04: Tata Consumer Products AGM 2025 (18 pages, 6 items), uploaded through the API with `PIPELINE_EXTRACTOR=teacher` and live Atlas: **58 s** from upload to `done`. Then checked in the browser: report table, drawer with rule checks, rationale and a verified citation |
| The override saves to `feedback` | ✅ a POST to `/analyses/{id}/feedback` stored it in Atlas; it shows on `/resolutions/{id}` and as "Analyst: For" in the report table |

### Delivered
- `app/reports/`: `models.py` (job, document, resolution, analysis, feedback records), `store.py` (a `ReportStore` interface; `MongoReportStore` on the SPEC 5 collections plus `jobs`, with indexes; `InMemoryReportStore` for tests and DB-less runs), `runner.py` (background job: parse, then the LangGraph pipeline with per-item progress, then save; one job at a time; failures are recorded on the job).
- Re-uploading the same PDF with the same company figures returns the existing analysis (`duplicate: true`) instead of paying for it again; a failed job is retried.
- `app/pipeline/factory.py`: builds providers on the first job (`PIPELINE_EXTRACTOR=student|teacher`). The teacher is the student's fallback and the reasoner; without it, items go to NEEDS_REVIEW.
- Uploads are checked for the `%PDF-` header and a size limit (`MAX_UPLOAD_MB`, default 25); write endpoints need `X-API-Key`.
- `guess_company` moved from `scripts/harvest_notices.py` to `app/parsing/company.py` (used for the report header).
- Frontend: a small path router (no router dependency), shared API client and types, a Fraunces display face with semantic colours (FOR green, AGAINST oxblood, NEEDS_REVIEW amber; LAW tags filled, POLICY outlined). Citations show the quote on hover; click opens the regulation chunk with the quoted span highlighted. Guardrail adjustments and pipeline flags are shown in the drawer.
- Fix: the Vite proxy now targets `127.0.0.1:8000`. On Windows, Node resolved `localhost` to `::1` and every API call returned 502.
- New dependency: `python-multipart` (approved 2026-10-04), which FastAPI needs for multipart uploads.

### Tests
`tests/test_documents_api.py`: upload → job stages (parsing → extracting → analysing → done) → report → resolution → feedback, duplicate reuse, auth, non-PDF (415), size limit (413), a PDF with no notice failing the job with a readable error, 404s, `/eval/latest`. 278 backend tests pass; the frontend builds with `tsc` and passes oxlint with no warnings.

### Not done yet
- Hand-labelling ≥ 150 gold items (Deepesh), needed for Phase 7.
- The Evaluation page shows a generic metric list until Phase 7 defines the run format.
- Request IDs and per-node latency logs: Phase 8.


## Phase 5: Decision engine + LangGraph pipeline (built 2026-10-04; accepted)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| `config/policy.yaml`, rule functions, LLM reasoner, constraint enforcement, LangGraph graph wiring all nodes | ✅ `app/rules/`, `app/llm/reasoner.py`, `app/pipeline/constraints.py`, `app/pipeline/graph.py` (`parse → extract → validate → retrieve → rule_check → reason → assemble`) |
| Unit tests for every rule (pass/fail/NA/insufficient) | ✅ `tests/test_rules.py`: 70 cases over all 11 rules, each status a rule can return. A test fails if a policy rule has no cases or names an unregistered check. Some rules can't return every status (e.g. `ID_SPECIAL_RESOLUTION` is only PASS/FAIL) |
| Integration test: a full notice end-to-end with mocked LLMs | ✅ `tests/test_pipeline.py`: the real ITC 2025 notice (11 items) with fake student/teacher/reasoner/retriever. It covers teacher fallback, a LAW failure flipping FOR to AGAINST, invented citations being dropped, a missing reasoner, and retrieval/extraction failures degrading to flags |
| Constraint violations impossible by test | ✅ `tests/test_constraints.py` runs every combination (4 recommendations × 7 confidences × 5 citation sets × 100 finding sets = 14,000 cases) and asserts all three SPEC 6.2 constraints on each |

### Live check (not part of the acceptance criteria)
`uv run python -m scripts.analyse_notice tests/fixtures/notices/devyani_2025.pdf --extractor teacher`: real Gemini extraction and reasoning, live Atlas retrieval, 6 items, about 1 minute.
- Adopting accounts → FOR (1.00). Two rotation re-appointments → NEEDS_REVIEW: the extraction has no age, so the Reg 17(1A) LAW check returns INSUFFICIENT_DATA. Two auditor items → FOR: "second term" read as 5 prior years (10 ≤ 10 for a firm). WTD pay → NEEDS_REVIEW (the reasoner's own call).
- On one item the reasoner cited a chunk that was not retrieved; enforcement dropped it and lowered confidence 0.95 → 0.80.
- The first run found two gaps, now fixed with tests: an auditor named only in the title, and "second/third term" wording when prior years are not stated.

### Design notes
- **Rules return INSUFFICIENT_DATA when the notice lacks a fact.** Company turnover (RPT materiality) and net profit (Reg 17(6)(e)) are not in the extraction. They can be passed as `CompanyFacts` (`--turnover-cr`, `--net-profit-cr`); otherwise those checks only decide when the answer is certain without them. For example, a value above Rs 5,000 crore is material at any turnover, and pay within Rs 5 crore is below the Reg 17(6)(e) threshold at any profit.
- **Prior tenure**: stated years are used first, then "first/second/third term" wording; a plain "appointment" counts as a first term. A re-appointment with neither gives INSUFFICIENT_DATA.
- **Constraint order**: invalid citations are dropped first (−0.15 confidence each; quotes must be at least 12 characters and are matched with whitespace normalised). Then a LAW FAIL turns FOR into AGAINST. Then a LAW INSUFFICIENT_DATA or confidence < 0.6 forces NEEDS_REVIEW. Every change is recorded in `adjustments`.
- **`validate` node**: the notice's item number and its "as a Special Resolution" wording override the model, and mismatches are flagged.
- **Failures degrade, never crash**: extraction failure → `EXTRACTION_FAILED` + NEEDS_REVIEW; retrieval error → `RETRIEVAL_FAILED` and no citations; reasoner failure → `REASONER_FAILED` + NEEDS_REVIEW.
- `policy.yaml`: added `agm_max_years: 1.25` to `RPT_OMNIBUS_VALIDITY`. s.96(1) allows at most 15 months between AGMs, which turns "valid until the next AGM" into a number.
- New dependency: `langgraph` (listed in SPEC 4).

### Not done yet (later phases)
- Persisting `documents` / `resolutions` / `analyses` and the upload API: Phase 6.
- Request IDs and per-node latency logging: Phase 8.

## Phase 4: Fine-tuning notebooks (built 2026-10-03; accepted 2026-10-04)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| `01_finetune_qlora.ipynb`, `02_eval_student.ipynb`, `03_export_checkpoint.ipynb` (GPU), `04_export_cpu.ipynb` (CPU-only) | ✅ generated by `scripts/build_notebooks.py`; code parses; data formatting and loss-masking markers checked on CPU |
| `LocalGGUFProvider` loads the model from HF Hub (cached) or a local path | ✅ implemented and unit-tested with a fake llama.cpp; `llama-cpp-python` 0.3.36 installs from prebuilt wheels |
| Deepesh runs the notebook on Colab; GGUF loads locally and returns valid JSON on 10 items | ✅ 2026-10-04: `smoke_student --n 10` gives 10/10 valid JSON on the first try (no repair), 9/10 `resolution_type` matching the teacher, median latency 69 s per item on the local CPU. Training: 1 epoch kept (val loss 0.191 → 0.182 over 2 epochs, no subset gain); exported from `checkpoint-130` with `04_export_cpu.ipynb` after the Colab GPU quota ran out |

### Runbook (Deepesh)
1. Create a Hugging Face **write** token. Put it in `.env` as `HF_TOKEN=...`, and in Colab under *Secrets* as `HF_TOKEN` (notebook access on).
2. `uv run python -m scripts.push_sft_to_hub` uploads train/val plus eval prompts to the private dataset `<you>/proxylens-sft-v1`. Gold *labels* are never uploaded.
3. In Colab (Runtime → T4 GPU) open `notebooks/01_finetune_qlora.ipynb` and *Run all*. Expect about 1.5–2.5 h. On disconnect, run all again and it resumes from the Drive checkpoint. Output: private repos `<you>/proxylens-qwen3b-lora-v1` and `<you>/proxylens-qwen3b-gguf-v1`. If the session ends after training but before the uploads, export the latest Drive checkpoint with `03_export_checkpoint.ipynb` (T4), or with `04_export_cpu.ipynb` on a CPU-only runtime when the GPU quota is used up.
4. Set `STUDENT_GGUF_REPO=<you>/proxylens-qwen3b-gguf-v1` in `.env`, then run `uv sync --extra student` and `uv run python -m scripts.smoke_student --n 10`. That is the acceptance check.
5. Later (after gold labelling): `notebooks/02_eval_student.ipynb` writes base vs fine-tuned predictions to `eval/results/` for Phase 7.

### Delivered
- **Notebook 01** (Unsloth + TRL): `unsloth/Qwen2.5-3B-Instruct-bnb-4bit`, LoRA r=16/α=16/dropout 0 on all attention + MLP projections, lr 2e-4 cosine, 1 epoch (2 tried; no gain), effective batch 16 (1 x 16), fp16 on T4, seed 3407, loss on assistant tokens only (`train_on_responses_only`). It logs train/eval loss plus **val JSON validity and type accuracy after every epoch** (32-item subset; full val at the end), checkpoints to Drive every 10 steps and resumes automatically, pushes the LoRA + `metrics.json`, and exports a merged `Q4_K_M` GGUF named `proxylens-q4_k_m.gguf`. It tolerates TRL's `max_seq_length`→`max_length` rename.
- **Notebook 02**: base (zero-shot, same prompt) and fine-tuned predictions on `test` (gold-split prompts) or `val`, with greedy decoding, saved per model as `eval/results/<run_id>.json` (format in `eval/README.md`). Metrics are computed in the repo, not the notebook.
- `app/llm/local_gguf.py`: llama.cpp provider (lazy load, thread lock, `n_ctx` 4096, optional grammar-constrained JSON, HF Hub download with caching or a local path). `app/llm/fallback.py`: student → one repair → teacher, recording whether the fallback fired. `create_student()`.
- `scripts/push_sft_to_hub.py`, `scripts/smoke_student.py`, `scripts/build_notebooks.py`; `student` optional extra (`llama-cpp-python`) from the project's CPU wheel index.

### Checks done without a GPU
- Token lengths with the Qwen tokenizer: longest train example **4,093 tokens** (median about 1,460), longest answer 872, so 4,096 context and 1,024 new tokens never truncate.
- The schema cell copied into the notebook validates all 1,504 teacher answers.
- Qwen's chat template produces exactly one `<|im_start|>user
` and one `<|im_start|>assistant
` per example, the assistant span starts exactly at the JSON answer, and Qwen's default system prompt is not injected.
- A test fails if the committed notebooks drift from `scripts/build_notebooks.py`.

### Not verified (needs Colab)
The notebooks haven't run end to end on a GPU. Unsloth/TRL API changes are the main risk: the config helper handles the known rename, and anything else will surface in the first cells.

## Phase 3: Teacher pipeline + data collection (done 2026-10-03, pending review)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| ≥ 1,500 validated teacher-labelled resolutions | ✅ **1,504 / 1,504 valid** (all on the first try), $4.55 total |
| Company-grouped splits | ✅ train 1,367 items / 218 companies · val 137 / 22 · gold 184 / 30 (never sent to the teacher) |
| Labelling UI usable for the 150 gold items | ✅ `/label` page + API, verified in the browser; 184 candidates waiting |

### Decisions (made with Deepesh)
- **Teacher: `google/gemini-3.8-flash` via OpenRouter** instead of Vertex AI. Measured cost: ~$0.003 per item with reasoning effort `low`.
- **Notices collected by search + polite download**, since BSE/NSE/India Code block automated bulk access. 297 notices (2016–2026, mostly FY23–FY26) from the BSE filing archive, a Business Standard mirror of BSE filings, and company sites.
- **Gold-labelling tool is a React route** (`/label`), not Streamlit, so there's no new dependency.

### Delivered
- `app/llm/`: provider interface (`generate_json`), `OpenRouterProvider` (strict JSON schema, `usage.cost`, retry with backoff that honours `Retry-After`, reasoning-effort control), `strict_json_schema()`, lenient JSON parsing, extraction prompt shared by teacher, student and SFT export, and `extract()` with validation plus one repair retry.
- `app/dataset/`: notice manifest (CSV), deterministic company-grouped split (80/10/10 by hashed, normalised name), chat-format SFT records, JSONL helpers.
- `app/gold/` + `/api/v1/gold/*`: file-backed gold store (append-only; latest label wins) and endpoints. Writes need `X-API-Key` and fail closed when no key is configured.
- `frontend/src/label/`: three-pane labelling page (items + progress, source text, form; Save / Skip with reason / Next). It never shows teacher output, so the gold labels stay independent.
- Scripts: `collect_notices` (manifest sync / manual mode), `harvest_notices` (URL list → validated notices with company names; rejects covering letters, corrigenda, newspaper ads, >30-item parses), `segment`, `teacher_label` (budget cap, dry-run cost estimate, resumable, skips the gold split), `make_sft` (optional two-teacher agreement filter), `dataset_card`, `make_notice_fixtures`.
- `data/DATASET_CARD.md`, generated from the data.

### Problems found and fixed along the way
- **Strict-schema bug:** the schema helper dropped the `title` *property* along with the `title` annotation keyword, so 0/5 of the first smoke-test items validated. Fixed, with a regression test.
- **Hidden reasoning cost:** Gemini 3.8 Flash is a thinking model; reasoning effort `low` cut cost about 5× with no validity loss.
- **Rate limits:** 1 in 3 calls hit HTTP 429 at 6 workers and was wrongly recorded as "done". Fixed: provider failures are retried on the next run, backoff honours `Retry-After`, and the run uses 2 workers.
- **Parser gaps found by new notices:** Roman-numeral item numbering (I., II.) and allottee tables numbered 1–99; newspaper-ad filings that parse as notices; company names from the wrong sentence. All fixed and covered by tests. The 14 fixture notices still split 14/14, and re-segmenting the full collection after the last parser fix changed 0 notices.

### Label sanity check
Where the notice says explicitly "as a Special/Ordinary Resolution", the teacher's `is_special_resolution` agrees on **975 / 981 (99.4%)**. Some of the 6 disagreements look like parser-hint errors rather than teacher errors. A proper accuracy number needs the human gold set (Phase 7).

### Known limits
- Teacher labels are not human-verified; the dataset leans to small and mid caps (see the dataset card).
- Company names come from heuristics plus 4 manual fixes; an undetected error could put one company in two splits.
- `data/` is gitignored except the manifest and dataset card; rebuild with the scripts.

### Next
Deepesh: hand-label ≥150 gold items at `/label` (`API_KEY` is set in `.env`; paste it into the page). Me: Phase 4 fine-tuning notebooks.

## Phase 2: PDF parsing + segmentation (done 2026-10-02, pending review)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| ≥ 10 sample notices in `tests/fixtures/` | ✅ 14 real notices (12 AGMs, 1 EGM, 1 postal ballot), 3 of them held out |
| Segmentation matches hand-counted items on ≥ 9 of 10 | ✅ **14/14** (11/11 tuning set, 3/3 held out) |
| Unit tests cover edge cases | ✅ agenda, statements, header stripping, end-to-end |

**How the counts were made:** each notice's agenda was read and its items counted by hand *before* the splitter was written; the counts live in `tests/fixtures/notices/manifest.yaml`.

**Overfitting caveat:** the splitter's rules were developed while looking at the 11 tuning notices, so 11/11 overstates generality. Three more notices (SIS, Kamdhenu, Grovy) were counted and then parsed once with no code changes: **3/3 item counts matched**. Grovy then showed statements printed before the formal "Explanatory Statement" heading; that fix came after, so Grovy's *statement alignment* is not an unseen result.

### Delivered (`app/parsing/`)
- `pdf_text.py`: PyMuPDF text per page; strips control/bullet glyphs, page-number lines and running headers/footers (lines repeated on ≥30% of pages; must contain words, so bare "1." markers survive).
- `agenda.py`: notice start ("hereby given", skipping cover letters and annual-report pages), agenda end (NOTES / By Order of the Board / capitalised statement heading), item splitting with ORDINARY/SPECIAL sections:
  - "Item No. N" headings always start items (and the numbers may repeat, as in MSTC).
  - A bare "N." starts an item only if it is the next number, the notice hasn't switched to "Item No." headings, and it doesn't continue a numbered list inside the current item (unless the previous line closes a quoted resolution).
  - An agenda summary table (Persistent) is detected when the numbering restarts at 1 with a matching first item; its titles then vet every later item.
  - `resolution_kind_hint` from "as a Special/Ordinary Resolution".
- `statements.py`: finds the Section 102 statement (capitalised heading, mixed-case heading with a dash, or the first real "Item No." heading after the agenda), splits at "Item No(s)." headings ("8 & 9", "3-4", "4 to 6"), ignores in-text references ("Item No. 4 of the Notice").
- `notice.py`: `parse_notice_pdf()` → `ParsedNotice(meeting_type, page_count, items[NoticeItem])`; aligns statements (shared statements go to every listed item; repeated numbers go to the special-business item; an unheaded statement goes to the sole special item).
- `scripts/make_notice_fixtures.py` rebuilds fixtures from `source_url`s; images are downsampled (~21 MB → ~10 MB) and each fixture's extracted text is verified identical to the original.

### Notices rejected as fixtures
- A Simplex Infrastructures EGM *corrigendum* (scanned/OCR, no resolutions), a Tata Steel newspaper advertisement, a Jubilant Pharmova cover letter, and six BSE covering letters: none are notices. TCS and Infosys returned 403 and NSE archives refused connections; no workaround attempted.

### Known limits
- A numbered list inside a resolution that runs exactly into the next item's number, with no closing quote and no summary table, swallows the next item (tested and documented in `test_parsing_agenda.py`).
- Statements can be long (Persistent item 7: ~32k chars, including director profiles). Phase 3 prompts should truncate.
- Text-based PDFs only; scanned notices are out of scope (SPEC §2).

### Verified locally
- `ruff`, `ruff format`, `mypy --strict`: clean. `pytest`: 122 passed, 1 skipped (opt-in Atlas test).

## Phase 1: Regulation corpus + vector search (done 2026-10-02, pending review)

### Status against acceptance criteria
| Criterion | Status |
|---|---|
| 20 hand-written queries in `tests/retrieval_cases.yaml` | ✅ 14 LODR + 6 Companies Act |
| recall@6 ≥ 0.8 | ✅ **1.00 (20/20)**; 0.95 before one case label was fixed (see below). `RUN_ATLAS_TESTS=1` acceptance test passes against Atlas |
| `/regulations/search` endpoint works | ✅ verified live against Atlas (vector, hybrid, input validation) |
| Rule params/citations verified with `source_url` + `as_of` | ✅ LODR rules verified · ⚠️ Companies Act rules match the 2013 text only, so they stay `verified: false` |

**Companies Act caveat:** India Code, MCA and ICSI were all unreachable (403/404), both for automated downloads and for Deepesh's browser. With Deepesh's approval, the Act comes from **PRS India's copy as enacted on 29 Aug 2013**. Every Companies Act chunk has `as_of: 2013-08-29` and a `notes` warning that is returned by the search API. Sections amended since (e.g. 2017 changes to s.197, s.188, s.196) may not match current law. Swap in the amended text when India Code is reachable.

**One test case was relabelled after results were seen.** The "criteria of independence" query originally expected only LODR Reg 16(1), because it was written before the Act was loaded. Retrieval returned Companies Act s.149(6), which is the statutory definition and an equally correct answer, so s.149(6) was added to the expected units. Before that change, recall@6 was 0.95.

### Delivered
- **Sources:** both are downloaded once and cached by `scripts/build_corpus.py`.
  - The official consolidated SEBI LODR 2015, *amended up to 14 July 2026*, from sebi.gov.in (robots.txt allows it). `as_of` is read from the PDF's own "Amended up to" banner.
  - The Companies Act 2013 as enacted, from PRS India.
- **`app/corpus/`:** cleaning (strips page numbers, the amendment-footnote block on each page, and inline markers like `134[`, `[***]`, `]210`), legal-unit parsing (regulation → sub-regulation, with headings and chapters; numbering must advance in small steps, so list items and cross-references don't start new units), paragraph-aware chunking (≤280 words ≈ 400 BGE tokens; longer units split with 40-word overlap, same citation), and `applies_to` tagging from `config/corpus_tags.yaml`.
- **Corpus:** 447 chunks in Atlas `proxylens.regulations`, embedded with `BAAI/bge-base-en-v1.5` (local CPU):
  - 303 LODR chunks: all 57 regulations of Chapters I–IV, Schedule II (Parts A–E) and Schedule XII.
  - 144 Companies Act chunks: sections 14, 42, 62, 102, 123, 139, 142, 148, 149, 152, 160, 177, 178, 180, 188, 196 and 197, plus Schedules IV and V.
- **Companies Act parser** (`app/corpus/companies_act.py`): the Gazette layout puts section headings in the page margin, so pages are rebuilt from line geometry. Margin notes are matched to the section start at the same height, soft hyphens are mended, and running headers and cross-reference notes ("23 of 1959.") are dropped.
- **Indexes:** `regulations_vec` (768-d cosine, filters on `applies_to` and `source`) and `regulations_text` (Atlas Search) created with `create_search_index` (`scripts/create_indexes.py`).
- **Retrieval:** `app/retrieval/search.py`, i.e. `retrieve(query, resolution_type, k, hybrid=False)` using `$vectorSearch` with an `applies_to` filter. Optional hybrid mode fuses it with `$search` via reciprocal-rank fusion. On the final corpus both modes score the same, so pure vector stays the default: it's one query instead of two.
- **API:** `GET /api/v1/regulations/search?q=&type=&k=&hybrid=`.
- **Eval:** `scripts/eval_retrieval.py` prints per-query hits and misses. `tests/test_retrieval_atlas.py` is the acceptance test (opt-in, `RUN_ATLAS_TESTS=1`).
- **`config/policy.yaml`:** all SPEC §6.1 rules with params, citation, `source_url`, `as_of` and a `verified` flag. Check functions come in Phase 5.
- **Config:** OpenRouter teacher settings (`TEACHER_PROVIDER`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`) for Phase 3.

### Findings from verifying the rules against the official text
- **RPT materiality moved to Schedule XII** (w.e.f. 19.12.2025). It is tiered by consolidated turnover: 10% up to ₹20,000 cr; ₹2,000 cr + 5% above that up to ₹40,000 cr; ₹3,000 cr + 2.5% beyond that, capped at ₹5,000 cr. The spec cited Reg 23(1) only.
- **Reg 25(2A): every independent director appointment or re-appointment needs a special resolution**, not only second terms. `ID_SECOND_TERM_SPECIAL` is replaced by `ID_SPECIAL_RESOLUTION`.
- **Omnibus RPT approvals expire at the next AGM**, or after one year if granted at another general meeting (Reg 23(4) provisos). This is added as the LAW rule `RPT_OMNIBUS_VALIDITY`, so `POL_RPT_NO_CAP` now only checks for a monetary cap.
- Reg 17(1A) (age 75), 17(1D) (approval every 5 years) and 17(6)(e) (promoter pay: ₹5 cr or 2.5% of net profit, 5% aggregate) match the spec.

### Verified locally
- `ruff`, `ruff format`, `mypy --strict` (app, tests, scripts): clean.
- `pytest`: 71 passed, 1 skipped (the opt-in Atlas acceptance test, which passes with `RUN_ATLAS_TESTS=1`).
- Live: corpus build, index creation, `scripts.eval_retrieval`, and `/regulations/search` against Atlas.

### Deviations from SPEC
- **Extra Companies Act sections tagged:** s.14, 42, 62, 123, 142 and 148 besides the listed ones, so ARTICLES, CAPITAL_RAISE, ESOP, DIVIDEND and cost-auditor resolutions have governing text.
- **Unit tests use a small in-memory fake instead of `mongomock-motor`** for writes. mongomock can't execute PyMongo 4.x `ReplaceOne`.
- **Chunks carry `notes`** (caveats such as the pre-amendment warning, also returned by the search API).
- **Chunks carry a `heading` field** (e.g. "Related party transactions"). It is embedded together with the citation for context.

### Notes for later phases
- First search after startup takes about 12 s while BGE loads. For Cloud Run (Phase 8), preload at startup or bake the model into the image.

## Phase 0: Scaffold (done 2026-10-02)
- Repo scaffold, config, `/healthz` with DB ping, Dockerfiles + compose (with Atlas Local), React shell, CI, pre-commit.
- Verified: CI green, including the compose smoke test; `/healthz` returns 200 against the Atlas cluster.
- Deviations: PyMongo async instead of the deprecated `motor`; compose adds a `mongo` service; frontend lint uses `oxlint`.

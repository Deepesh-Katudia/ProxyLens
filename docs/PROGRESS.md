# Progress

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

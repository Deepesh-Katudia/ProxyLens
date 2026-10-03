# Progress

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

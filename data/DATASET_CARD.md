# ProxyLens dataset card

_Generated 2026-10-03 by `scripts/dataset_card.py`._

## What it is

Agenda items from Indian listed companies' general-meeting notices (AGM, EGM, postal ballot), each paired with a structured `ResolutionExtraction` (SPEC 5.1) produced by a teacher LLM. Used to fine-tune a small student model. The test set is labelled by hand and never by the teacher.

## Sources

297 notices from 270 companies, segmented into 1688 agenda items by `app/parsing`. Notices are public regulatory filings, fetched politely (one at a time, identifying User-Agent, cached) from:

| Host | Notices |
|---|---|
| bseindia.com | 234 |
| www.bseindia.com | 31 |
| bsmedia.business-standard.com | 13 |
| www.bajajhousingfinance.in | 1 |
| dil-rjcorp.com | 1 |
| www.msei.in | 1 |
| www.grovyindia.com | 1 |
| itcportal.com | 1 |
| www.jswinfrastructure.in | 1 |
| www.kamdhenulimited.com | 1 |
| mediassist.in | 1 |
| www.mstcindia.co.in | 1 |
| ncclimited.com | 1 |
| jaispring.com | 1 |
| www.lumaxworld.in | 1 |
| adityabirlacapital.com | 1 |
| www.nhpcindia.com | 1 |
| www.persistent.com | 1 |
| www.dizcoverpraveg.com | 1 |
| sisindia.com | 1 |
| www.tataconsumer.com | 1 |
| xtranetindia.com | 1 |

| Meeting type | Notices |
|---|---|
| AGM | 259 |
| EGM | 18 |
| POSTAL_BALLOT | 6 |
| UNKNOWN | 14 |

## Splits (grouped by company, no company in two splits)

| Split | Items |
|---|---|
| train | 1367 |
| val | 137 |
| gold candidates (for human labels) | 184 |

| Split | Companies |
|---|---|
| gold | 30 |
| train | 218 |
| val | 22 |

## Teacher labels

Teacher: `google/gemini-3.8-flash` via OpenRouter, temperature 0, strict JSON schema, one repair retry.

| Metric | Value |
|---|---|
| items sent to the teacher | 1504 |
| calls retried after provider errors (rate limits) | 47 |
| model replied | 1504 |
| valid on first try | 1504 |
| valid after repair | 1504 |
| total cost (USD) | 4.55 |

Filtering before export: {}

### Resolution types (train)

| Type | Items |
|---|---|
| ADOPT_FINANCIALS | 217 |
| DIRECTOR_REAPPOINT_ROTATION | 216 |
| INDEPENDENT_DIRECTOR_APPOINT | 202 |
| RELATED_PARTY_TRANSACTION | 110 |
| NON_INDEPENDENT_DIRECTOR_APPOINT | 99 |
| MANAGERIAL_REMUNERATION | 84 |
| DIVIDEND | 79 |
| AUDITOR_APPOINT | 68 |
| OTHER | 58 |
| AUDITOR_REMUNERATION_COST | 57 |
| ESOP | 51 |
| BORROWING_LIMITS | 48 |
| CAPITAL_RAISE | 43 |
| ARTICLES_OR_MOA_AMENDMENT | 35 |

## Known biases and limits

- Collected via web search of the BSE filing archive and company sites, so it over-represents small and mid caps that file full notices on BSE; NSE-only filings are missing (the NSE archive blocks automated access).
- English, text-based PDFs only; scanned notices and newspaper advertisements were rejected.
- Notice years range mostly from FY23 to FY26, with a few older notices.
- Segmentation is automatic (14/14 on hand-counted fixtures, but not perfect at this scale); a wrong split produces a malformed item.
- Labels come from one teacher model and are not human-verified; errors in the teacher become errors in the student.
- Company names were extracted heuristically and fixed by hand where wrong; an undetected name error could place one company in two splits.

## License notes

Source notices are public filings under SEBI LODR and the Companies Act. The repo stores derived text and labels, not the source PDFs (except 14 test fixtures); `data/raw/notices/manifest.csv` lists every source URL so the set can be rebuilt.

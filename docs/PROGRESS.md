# Progress

## Phase 0: Scaffold (done 2026-10-02, pending review)

### Delivered
- Repo layout per SPEC §11 (empty packages for later phases).
- `pyproject.toml` (uv, Python 3.11 pinned) with ruff, strict mypy and pytest config; `uv.lock`.
- `app/config.py`: pydantic-settings, all SPEC §12 variables; secrets are `SecretStr`.
- `app/main.py`: `create_app()` factory; Mongo client opened and closed in the lifespan.
- `GET /healthz` and `GET /api/v1/healthz`: pings MongoDB. Returns `200` when the DB is reachable, `503` when it is unreachable or not configured. `model` stays `not_loaded` until Phase 4.
- `Dockerfile` (api, non-root, honours Cloud Run `$PORT`), `frontend/Dockerfile` (nginx, proxies `/api`), `docker-compose.yml` (mongo + api + frontend).
- Frontend: React 19 + Vite + TS + Tailwind v4 shell that shows API health and the disclaimer.
- `.github/workflows/ci.yml`: backend (ruff, format, mypy, pytest), frontend (oxlint, build), docker (build both images + compose smoke test hitting `/healthz`).
- `.pre-commit-config.yaml`, `.env.example`, `.gitignore`, `.dockerignore`.

### Verified locally
- `ruff check`, `ruff format --check`, `mypy --strict`: clean.
- `pytest`: 10 passed (health 200/503 paths, config parsing, secret masking, real client ping against an unreachable server).
- `uvicorn` boots; `/healthz` returns 503 `not_configured` with no URI.
- `npm run lint` and `npm run build`: clean.

### Not verified yet
- `docker compose up` was **not** run: Docker isn't installed on the dev machine. The CI `docker` job runs the compose smoke test, so a green CI run is the check for this criterion.
- CI hasn't run yet; the repo isn't on GitHub yet.

### Deviations from SPEC
- **`pymongo` async (`AsyncMongoClient`) instead of `motor`.** Motor is deprecated in favour of PyMongo's native async API, which has the same shape. `mongomock-motor` stays in dev deps for later unit tests.
- **Compose adds a `mongo` service** (`mongodb/mongodb-atlas-local`), so `/healthz` and, later, `$vectorSearch` work offline. Set `MONGODB_URI` in `.env` to use Atlas instead.
- **Frontend lint uses `oxlint`**, the current Vite template default, instead of ESLint.

## Next: Phase 1 (regulation corpus + vector search)
Needs from Deepesh: an Atlas connection string with Vector Search enabled (or Docker for the local Atlas image).
New dependencies to approve (all in SPEC §4): `sentence-transformers`, `pymupdf`, `pyyaml` (not in §4; for `tests/retrieval_cases.yaml` and `policy.yaml`), `httpx` as a runtime dep for corpus download.

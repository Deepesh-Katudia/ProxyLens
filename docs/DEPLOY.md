# Deploying ProxyLens to Google Cloud

Two Cloud Run services, built by Cloud Build from this repo. No local Docker is needed.

```
browser ──> proxylens-web (nginx, 1 vCPU)  ──/api──>  proxylens-api (FastAPI, 4 vCPU / 8 GiB)
                 static React app                       ├─ fine-tuned GGUF (baked in the image)
                                                        ├─ BGE embedder (baked in the image)
                                                        ├─ MongoDB Atlas (reports, regulation vectors)
                                                        └─ OpenRouter (teacher fallback + reasoner)
```

| Piece | Choice | Why |
|---|---|---|
| API | Cloud Run, 4 vCPU / 8 GiB, concurrency 2, min 0, max 2 | SPEC Phase 8. One analysis job runs at a time per instance (llama.cpp holds one context). |
| CPU | `--no-cpu-throttling` | Analysis runs as a background task *after* the upload returns. With request-based CPU, Cloud Run throttles the CPU then and the job stalls. |
| Models | Baked into the image | A cold start then reads 2.4 GB from the image instead of downloading it from HF Hub. `HF_HUB_OFFLINE=1` makes sure nothing is fetched at runtime. |
| Model load | `PRELOAD_MODELS=true` | BGE and the GGUF load in a background thread at startup, so the first upload doesn't pay for it. The port opens immediately, so startup probes pass. |
| Frontend | nginx on Cloud Run, proxying `/api` | Same image as docker compose (`API_UPSTREAM` differs), same origin for the browser (no CORS), one toolchain. |
| Secrets | Secret Manager | `MONGODB_URI`, `API_KEY` and `OPENROUTER_API_KEY` at runtime; `HF_TOKEN` at build time only (a BuildKit secret, never in an image layer). |
| Identities | 4 service accounts | `proxylens-run` (API) reads its three secrets and nothing else. `proxylens-web` (nginx) has no roles. `proxylens-build` pushes images and deploys; its `run.admin` is project-wide (needed for `--allow-unauthenticated`), so use a project dedicated to ProxyLens. `proxylens-deploy` (optional, GitHub) can only submit builds, and only from `main` or a `v*` tag. |
| Logs | JSON on stderr | Cloud Logging parses `severity`/`message`. Each line carries `request_id`, and each pipeline node logs `node` and `duration_ms`. |

There is no Vertex AI service account: the teacher runs on OpenRouter (decided in Phase 3), so nothing calls Vertex.

## 1. Prerequisites (once)

1. **Install the gcloud CLI:** https://cloud.google.com/sdk/docs/install. Then:
   ```bash
   gcloud auth login
   ```
2. **Create a GCP project with billing enabled**, and note its id:
   ```bash
   gcloud projects create proxylens-demo-123   # or use the console
   gcloud billing projects link proxylens-demo-123 --billing-account=XXXXXX-XXXXXX-XXXXXX
   ```
3. **Set a budget alert** so a stuck instance can't surprise you:
   ```bash
   gcloud billing budgets create --billing-account=XXXXXX-XXXXXX-XXXXXX \
     --display-name="proxylens" --budget-amount=5USD \
     --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
   ```
4. **`.env` must have** `MONGODB_URI`, `API_KEY`, `OPENROUTER_API_KEY` and `HF_TOKEN` (read access to the GGUF repo is enough).

The scripts are bash. On Windows, run them from Git Bash.

## 2. One-time GCP setup

```bash
PROJECT_ID=proxylens-demo-123 deploy/setup.sh
```

This enables Cloud Run, Artifact Registry, Cloud Build, Secret Manager and IAM. It creates:

- the `proxylens` image repository, keeping only the newest image of each service (about 4 GB, roughly $0.40/month; rolling back means redeploying an older commit);
- the service accounts;
- the four secrets, piped from `.env` over stdin;
- the IAM bindings;
- a source-staging bucket (uploads are deleted after 7 days).

Re-running it is safe. It adds a new secret version only when a value in `.env` has changed, so this is also how you rotate a key.

## 3. Let Cloud Run reach Atlas

Cloud Run has no fixed outbound IP. There are two options:

- **Simple (demo):** in Atlas, go to *Network Access → Add IP Address → `0.0.0.0/0`*. The cluster is still protected by its username and password, which live only in Secret Manager. Use a strong, generated password and a database user limited to the `proxylens` database.
- **Locked down:** route Cloud Run egress through a VPC with Cloud NAT and a reserved static IP, then allow only that IP in Atlas. This costs about $1/day for the NAT gateway. Add these flags to the API deploy step in `deploy/cloudbuild.yaml`:
  ```
  --network=default --subnet=default --vpc-egress=all-traffic
  ```
  To create the NAT:
  ```bash
  gcloud compute addresses create proxylens-egress --region=$REGION
  gcloud compute routers create proxylens-router --network=default --region=$REGION
  gcloud compute routers nats create proxylens-nat --router=proxylens-router --region=$REGION \
    --nat-custom-subnet-ip-ranges=default --nat-external-ip-pool=proxylens-egress
  ```

The deploy's smoke test calls `/api/v1/healthz`, which returns 503 until MongoDB answers. A network-access problem therefore fails the deploy instead of shipping a broken app.

## 4. Deploy

```bash
PROJECT_ID=proxylens-demo-123 deploy/deploy.sh
```

Cloud Build then:

1. builds the API image (with llama.cpp and the baked models) and the web image, in parallel;
2. pushes both, tagged with `git describe`;
3. deploys the API, then the web service pointing at the API's URL;
4. runs the smoke test through the web service.

The script prints the live URL at the end. The first build takes about 20 minutes. Later builds reuse the cached dependency and model layers.

Open the URL and paste the `API_KEY` into the upload page.

## 5. Deploy on a tag from GitHub (optional)

```bash
PROJECT_ID=proxylens-demo-123 GITHUB_REPO=Deepesh-Katudia/ProxyLens deploy/setup_github.sh
```

It needs the GitHub CLI (`gh`) to look up the repository's numeric id. It prints four values: add them as GitHub repository **variables**. None of them is a secret, and no service-account key exists anywhere: GitHub's OIDC token is exchanged through Workload Identity Federation. Only workflows in that repository running on `main` or a `v*` tag can get a token, so a pushed feature branch can't deploy.

After that, a tag deploys:

```bash
git tag v0.8.0 && git push origin v0.8.0
```

## Operating it

- **Logs:**
  ```bash
  gcloud logging read 'resource.labels.service_name="proxylens-api"' --limit=50
  ```
  In Logs Explorer, `jsonPayload.request_id="<id>"` shows one upload end to end: the HTTP line, the job start, and one `node … done` line per pipeline node with `jsonPayload.duration_ms`. Every response carries the ID in the `X-Request-ID` header.
- **Per-node latency:**
  ```
  jsonPayload.node:* AND jsonPayload.duration_ms>10000
  ```
  This shows slow nodes. `extract` dominates, because it is one student call per agenda item.
- **Roll back:**
  ```bash
  gcloud run services update-traffic proxylens-api --region=$REGION --to-revisions=<revision>=100
  ```
- **Rotate a secret:** change `.env`, re-run `deploy/setup.sh`, then redeploy. Secrets are pinned to `latest` at deploy time.

## Cold start and cost

<!-- Fill in with measured numbers after the first deploy (Phase 8 acceptance). -->

| What | Expected | Measured |
|---|---|---|
| Cold start to first byte (`/healthz`) | ~10–20 s (4 GB image, Python imports) | _to measure_ |
| Models ready after a cold start | +30–60 s (BGE + GGUF from the image) | _to measure_ |
| Student extraction, per item | well below the laptop's 41.6 s p50 (4 dedicated vCPUs) | _to measure_ |
| Idle cost | $0: min instances 0 | |
| Busy cost | about $0.0001/s (~$0.32/hour) per API instance: 4 vCPU + 8 GiB at instance-based prices; check the [pricing page](https://cloud.google.com/run/pricing) for your region | |

With CPU always allocated, an instance is billed from start until Cloud Run shuts it down, about 15 minutes after its last request. A single demo upload therefore costs roughly 15 minutes of instance time, about $0.08. Cloud Build adds a few cents per deploy, and Artifact Registry storage is about $0.10/GB-month (one ~4 GB API image).

To measure after deploying:

```bash
API=$(gcloud run services describe proxylens-api --region=$REGION --format='value(status.url)')
time curl -s $API/healthz        # cold (after ~20 min idle)
time curl -s $API/healthz        # warm
```

Then upload a notice and read the `extract` node's `duration_ms` and the per-item `latency_ms` in the report.

## Known limits

- **Jobs live in the instance that accepted the upload.** If Cloud Run replaces the instance mid-job, the job stays `extracting`; upload again. That can happen on a deploy or a crash, or on scale-in: the page polling `/jobs` normally keeps the instance busy, but a closed tab doesn't. `--min-instances=1` avoids scale-in for about $230/month; the real fix is the move to Cloud Tasks described in `app/reports/runner.py`.
- **`/label` (gold labelling) is a local tool.** The image has no `data/` directory.
- **Both services are public.** Writes need `X-API-Key`; reads (reports, regulation search) are open. Restricting the API to the web service would need nginx to mint ID tokens.

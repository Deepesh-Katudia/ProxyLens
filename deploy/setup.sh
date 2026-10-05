#!/usr/bin/env bash
# One-time GCP setup for ProxyLens (docs/DEPLOY.md, step 2). Safe to re-run.
#
#   PROJECT_ID=my-project deploy/setup.sh
#
# Secret values are read from .env (MONGODB_URI, API_KEY, OPENROUTER_API_KEY,
# HF_TOKEN) and piped to Secret Manager over stdin, so they never appear in
# arguments or shell history. A secret whose value is unchanged gets no new version.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

ENV_FILE="${ENV_FILE:-.env}"
# Relative temp dir: on Windows gcloud is a native program and can't open /tmp or <(...).
TMP_DIR="$(mktemp -d ./.deploy-tmp.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

env_value() {
  # The value of KEY in $ENV_FILE, without surrounding quotes or a trailing comment.
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%%[[:space:]]#*}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#\"}"; line="${line%\"}"
  printf '%s' "$line"
}

put_secret() {
  local id="$1" value="$2"
  if [[ -z "$value" ]]; then
    echo "!! $id: the value in $ENV_FILE is empty; skipped" >&2
    return
  fi
  if ! gcloud secrets describe "$id" >/dev/null 2>&1; then
    gcloud secrets create "$id" --replication-policy=automatic >/dev/null
  fi
  if [[ "$(gcloud secrets versions access latest --secret="$id" 2>/dev/null || true)" == "$value" ]]; then
    echo "   $id: unchanged"
  else
    printf '%s' "$value" | gcloud secrets versions add "$id" --data-file=- >/dev/null
    echo "   $id: new version added"
  fi
}

ensure_sa() {
  local name="$1" title="$2"
  if ! gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$name" --display-name="$title" >/dev/null
  fi
}

grant_secret() {
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$2" \
    --role=roles/secretmanager.secretAccessor --condition=None >/dev/null
}

[[ -f "$ENV_FILE" ]] || { echo "$ENV_FILE not found" >&2; exit 1; }
gcloud config set project "$PROJECT_ID" >/dev/null

echo "== Enabling APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com

echo "== Artifact Registry repo: $AR_REPO ($REGION)"
if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker \
    --location="$REGION" --description="ProxyLens images"
fi
# Keep only the newest image per package: each API image carries 2.4 GB of model
# weights, and storage above 0.5 GB is billed. Rolling back means redeploying.
cat > "$TMP_DIR/ar-cleanup.json" <<'JSON'
[
  {"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 1}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"olderThan": "1d"}}
]
JSON
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" \
  --policy="$TMP_DIR/ar-cleanup.json" --no-dry-run >/dev/null

echo "== Service accounts"
ensure_sa proxylens-run "ProxyLens API runtime"
ensure_sa proxylens-web "ProxyLens web runtime (no roles)"
ensure_sa proxylens-build "ProxyLens Cloud Build"

echo "== Secrets (from $ENV_FILE)"
put_secret "$SECRET_MONGODB_URI" "$(env_value MONGODB_URI)"
put_secret "$SECRET_API_KEY" "$(env_value API_KEY)"
put_secret "$SECRET_OPENROUTER_KEY" "$(env_value OPENROUTER_API_KEY)"
put_secret "$SECRET_HF_TOKEN" "$(env_value HF_TOKEN)"

echo "== IAM: runtime SA reads the three runtime secrets only"
for id in "$SECRET_MONGODB_URI" "$SECRET_API_KEY" "$SECRET_OPENROUTER_KEY"; do
  grant_secret "$id" "$RUN_SA"
done

echo "== IAM: build SA pushes images, deploys, and reads the HF token"
grant_secret "$SECRET_HF_TOKEN" "$BUILD_SA"
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$BUILD_SA" --role=roles/artifactregistry.writer >/dev/null
for role in roles/run.admin roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" \
    --role="$role" --condition=None >/dev/null
done
# run.admin is project-wide: --allow-unauthenticated needs setIamPolicy. Use a
# project dedicated to ProxyLens so it covers nothing else.
# Deploying a service that runs as an SA requires actAs on that SA.
for sa in "$RUN_SA" "$WEB_SA"; do
  gcloud iam service-accounts add-iam-policy-binding "$sa" \
    --member="serviceAccount:$BUILD_SA" --role=roles/iam.serviceAccountUser >/dev/null
done

echo "== Source staging bucket: gs://$STAGING_BUCKET"
if ! gcloud storage buckets describe "gs://$STAGING_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$STAGING_BUCKET" --location="$REGION" \
    --uniform-bucket-level-access
  echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}' > "$TMP_DIR/lifecycle.json"
  gcloud storage buckets update "gs://$STAGING_BUCKET" --lifecycle-file="$TMP_DIR/lifecycle.json"
fi
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="serviceAccount:$BUILD_SA" --role=roles/storage.objectViewer >/dev/null

cat <<EOF

Done. Next:
  1. Atlas: allow Cloud Run egress (docs/DEPLOY.md, step 3).
  2. Deploy: PROJECT_ID=$PROJECT_ID deploy/deploy.sh
EOF

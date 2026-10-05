#!/usr/bin/env bash
# Build and deploy both services with Cloud Build (no local Docker needed).
#
#   PROJECT_ID=my-project deploy/deploy.sh
#
# Images are tagged with `git describe`, so a Cloud Run revision maps to a commit.
# The first build takes ~20 min (torch, llama.cpp, 2.4 GB of models); later builds
# reuse cached layers when only app code changed.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

TAG="${TAG:-$(git describe --tags --always --dirty | tr -c 'A-Za-z0-9_.\n-' '-')}"
echo "== Deploying $TAG to $PROJECT_ID ($REGION)"

gcloud builds submit . \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --config=deploy/cloudbuild.yaml \
  --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
  --gcs-source-staging-dir="gs://$STAGING_BUCKET/source" \
  --substitutions="_REGION=$REGION,_AR_REPO=$AR_REPO,_API_SERVICE=$API_SERVICE,_WEB_SERVICE=$WEB_SERVICE,_RUN_SA=$RUN_SA,_WEB_SA=$WEB_SA,_TAG=$TAG,_TEACHER_MODEL=$TEACHER_MODEL,_GGUF_REPO=$STUDENT_GGUF_REPO,_GGUF_FILE=$STUDENT_GGUF_FILE"

WEB_URL="$(gcloud run services describe "$WEB_SERVICE" --project="$PROJECT_ID" \
  --region="$REGION" --format='value(status.url)' | tr -d '\r')"
echo
echo "Live: $WEB_URL"

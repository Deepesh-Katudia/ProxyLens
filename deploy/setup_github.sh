#!/usr/bin/env bash
# Optional: let GitHub Actions deploy on a version tag, with no service-account key
# (Workload Identity Federation). Run after deploy/setup.sh.
#
#   PROJECT_ID=my-project GITHUB_REPO=Deepesh-Katudia/ProxyLens deploy/setup_github.sh
#
# Only workflows in GITHUB_REPO can use the pool, and the deployer can do no more
# than submit builds that run as the build service account.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

: "${GITHUB_REPO:?set GITHUB_REPO=owner/repo}"
POOL="github"
PROVIDER="proxylens-repo"
DEPLOY_SA="proxylens-deploy@${PROJECT_ID}.iam.gserviceaccount.com"
# tr: on Windows gcloud prints CRLF, and command substitution keeps the \r.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' | tr -d '\r')"
REPO_ID="$(gh api "repos/${GITHUB_REPO}" --jq .id | tr -d '\r')"
# Only version tags and main of this exact repository may get a token, so a pushed
# feature branch can't deploy. The numeric id survives a rename-and-recreate.
CONDITION="assertion.repository_id == '${REPO_ID}' && (assertion.ref.startsWith('refs/tags/v') || assertion.ref == 'refs/heads/main')"

if ! gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL" --location=global \
    --display-name="GitHub Actions"
fi
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="$CONDITION"
else
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global --attribute-condition="$CONDITION"
fi

if ! gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create proxylens-deploy --display-name="ProxyLens GitHub deployer"
fi
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}" \
  >/dev/null

# Submit builds and stream their logs; run them as the build SA; upload source.
for role in roles/cloudbuild.builds.editor roles/serviceusage.serviceUsageConsumer \
    roles/logging.viewer roles/run.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOY_SA" \
    --role="$role" --condition=None >/dev/null
done
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/storage.objectAdmin >/dev/null
# `gcloud builds submit` also reads the bucket's metadata.
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/storage.legacyBucketReader >/dev/null

cat <<EOF

Add these as GitHub repository *variables* (Settings > Secrets and variables >
Actions > Variables). None of them is a secret:
  GCP_PROJECT_ID     = $PROJECT_ID
  GCP_REGION         = $REGION
  GCP_WIF_PROVIDER   = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}
  GCP_DEPLOY_SA      = $DEPLOY_SA

Then a tag deploys:  git tag v0.8.0 && git push origin v0.8.0
EOF

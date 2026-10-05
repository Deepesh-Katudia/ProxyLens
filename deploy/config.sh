# Shared settings for the deploy scripts. Sourced, not run.
# Override any of these in the environment, e.g. `REGION=europe-west1 deploy/deploy.sh`.
# shellcheck shell=bash disable=SC2034  # variables are used by the scripts that source this

: "${PROJECT_ID:?set PROJECT_ID to your GCP project id}"
REGION="${REGION:-asia-south1}"

AR_REPO="${AR_REPO:-proxylens}"
API_SERVICE="${API_SERVICE:-proxylens-api}"
WEB_SERVICE="${WEB_SERVICE:-proxylens-web}"

# Runtime identity of the API service: reads its three secrets, nothing else.
RUN_SA="proxylens-run@${PROJECT_ID}.iam.gserviceaccount.com"
# Runtime identity of the web (nginx) service: no roles at all.
WEB_SA="proxylens-web@${PROJECT_ID}.iam.gserviceaccount.com"
# Identity of Cloud Build: builds, pushes, deploys.
BUILD_SA="proxylens-build@${PROJECT_ID}.iam.gserviceaccount.com"
# Source uploads for Cloud Build (so deployers don't need project-wide storage roles).
STAGING_BUCKET="${STAGING_BUCKET:-${PROJECT_ID}-proxylens-build}"

TEACHER_MODEL="${TEACHER_MODEL:-google/gemini-3.8-flash}"
STUDENT_GGUF_REPO="${STUDENT_GGUF_REPO:-deepeshkatudia/proxylens-qwen3b-gguf-v1}"
STUDENT_GGUF_FILE="${STUDENT_GGUF_FILE:-proxylens-q4_k_m.gguf}"

# Secret Manager ids -> the env var each one becomes (HF_TOKEN is build-time only).
SECRET_MONGODB_URI="proxylens-mongodb-uri"
SECRET_API_KEY="proxylens-api-key"
SECRET_OPENROUTER_KEY="proxylens-openrouter-key"
SECRET_HF_TOKEN="proxylens-hf-token"

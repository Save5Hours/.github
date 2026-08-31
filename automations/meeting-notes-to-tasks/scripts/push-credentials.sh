#!/usr/bin/env bash
# Prompt for n8n API keys (hidden input) and push them to Railway.
# Does not print secret values. Run from a laptop with `railway login`,
# or from this repo after `railway link` to save5hours-n8n / n8n.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export RAILWAY_CALLER="${RAILWAY_CALLER:-skill:use-railway@1.3.7}"
SERVICE="${RAILWAY_SERVICE_NAME:-n8n}"

if ! command -v railway >/dev/null 2>&1; then
  echo "Install the Railway CLI: npm i -g @railway/cli" >&2
  exit 1
fi
if ! railway whoami >/dev/null 2>&1; then
  echo "Run: railway login" >&2
  exit 1
fi

prompt_secret() {
  local label="$1"
  local value=""
  printf "%s: " "$label" >&2
  stty -echo
  IFS= read -r value
  stty echo
  printf "\n" >&2
  printf "%s" "$value"
}

prompt_plain() {
  local label="$1"
  local value=""
  printf "%s: " "$label" >&2
  IFS= read -r value
  printf "%s" "$value"
}

echo "OpenRouter is already on Railway n8n. This script still accepts a new key if you paste one."
echo "The remaining required secret is NOTION_API_KEY (internal integration, HQ Tasks connected)."
echo "Values go to Railway service ${SERVICE} (n8n Credentials UI is also fine)."
echo "Leave a line empty to skip that variable."
echo

OR="$(prompt_secret "OPENROUTER_API_KEY (sk-or-...)")"
NOTION="$(prompt_secret "NOTION_API_KEY (ntn_... or secret_...)")"
FOLDER="$(prompt_plain "GEMINI_NOTES_FOLDER_ID (Drive folder id, optional)")"
WEBHOOK="$(prompt_secret "N8N_WEBHOOK_SECRET (optional, leave empty to keep existing)")"

args=()
if [[ -n "$OR" ]]; then args+=("OPENROUTER_API_KEY=${OR}"); fi
if [[ -n "$NOTION" ]]; then args+=("NOTION_API_KEY=${NOTION}"); fi
if [[ -n "$FOLDER" ]]; then args+=("GEMINI_NOTES_FOLDER_ID=${FOLDER}"); fi
if [[ -n "$WEBHOOK" ]]; then args+=("N8N_WEBHOOK_SECRET=${WEBHOOK}"); fi
args+=("N8N_ACTIVATE_WORKFLOW=true")

if [[ ${#args[@]} -eq 1 ]]; then
  echo "Nothing to set besides activate. Need at least OpenRouter + Notion." >&2
  exit 1
fi

echo "Setting ${#args[@]} Railway variables (values redacted) and redeploying..."
# Do not echo args: they contain secrets.
railway variable set --service "$SERVICE" "${args[@]}" >/dev/null
timeout 90 railway redeploy --service "$SERVICE" --yes || railway up -y --ci --service "$SERVICE"

echo "Done. n8n: https://n8n-production-192e.up.railway.app/"
echo "Google Drive OAuth still needs Sign in inside n8n (Apps Script path does not)."

#!/usr/bin/env bash
# Deploy n8n to Railway from this folder. Requires railway login or RAILWAY_TOKEN.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.npm-global/bin:${PATH}"

if ! command -v railway >/dev/null 2>&1; then
  echo "Install the Railway CLI: npm i -g @railway/cli" >&2
  exit 1
fi

if ! railway whoami >/dev/null 2>&1; then
  echo "Railway is not authenticated in this environment." >&2
  echo "Run: railway login" >&2
  echo "Or export RAILWAY_TOKEN from https://railway.app/account/tokens" >&2
  exit 1
fi

if [[ -z "${N8N_ENCRYPTION_KEY:-}" ]]; then
  echo "Set N8N_ENCRYPTION_KEY before deploy (openssl rand -hex 32). Never rotate it." >&2
  exit 1
fi

railway up --ci
echo "Attach a volume at /home/node/.n8n and set WEBHOOK_URL after generating a domain."

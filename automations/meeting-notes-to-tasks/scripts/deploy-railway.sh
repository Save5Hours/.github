#!/usr/bin/env bash
# Create (if needed) and deploy n8n 1.123.75 on Railway from this folder.
# Requires: railway login OR RAILWAY_TOKEN, and N8N_ENCRYPTION_KEY.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.npm-global/bin:${PATH}"
PROJECT_NAME="${RAILWAY_PROJECT_NAME:-save5hours-n8n}"
SERVICE_NAME="${RAILWAY_SERVICE_NAME:-n8n}"
export PROJECT_NAME SERVICE_NAME

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

if [[ ! -f railway.toml ]]; then
  echo "Run this script from automations/meeting-notes-to-tasks (railway.toml missing)." >&2
  exit 1
fi

python3 - <<'PY'
import json, os, subprocess, sys

def run(args, check=True):
    print("+", " ".join(args), flush=True)
    r = subprocess.run(args, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout, end="" if r.stdout.endswith("\n") else "\n")
    if r.returncode != 0 and check:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(r.returncode)
    return r

who = run(["railway", "whoami"])
print("authenticated:", who.stdout.strip() or "(ok)")

status = run(["railway", "status", "--json"], check=False)
linked = status.returncode == 0
service = os.environ["SERVICE_NAME"]
project = os.environ["PROJECT_NAME"]

if not linked:
    init = ["railway", "init", "--name", project, "--json"]
    ws = os.environ.get("RAILWAY_WORKSPACE")
    if ws:
        init.extend(["--workspace", ws])
    run(init)
    run(["railway", "add", "--service", service, "--json"], check=False)

run(["railway", "up", "-y", "--ci", "--service", service])

vol = run(
    [
        "railway",
        "volume",
        "add",
        "--service",
        os.environ["SERVICE_NAME"],
        "--mount-path",
        "/home/node/.n8n",
        "--json",
    ],
    check=False,
)
if vol.returncode != 0:
    print("volume add skipped (likely already attached):", vol.stderr.strip())

run(["railway", "variable", "set",
     f"N8N_ENCRYPTION_KEY={os.environ['N8N_ENCRYPTION_KEY']}",
     "N8N_PORT=${{PORT}}",
     "N8N_PROTOCOL=https",
     "GENERIC_TIMEZONE=Europe/Zurich",
     "N8N_DEFAULT_BINARY_DATA_MODE=filesystem",
     "N8N_PROXY_HOPS=1",
     "EXECUTIONS_DATA_PRUNE=true",
     "EXECUTIONS_DATA_MAX_AGE=168",
     "N8N_SECURE_COOKIE=true",
     "--service", os.environ["SERVICE_NAME"],
     "--skip-deploys"])

listed = run(
    ["railway", "domain", "list", "--service", os.environ["SERVICE_NAME"], "--json"],
    check=False,
)
domain = None
if listed.returncode == 0 and listed.stdout.strip():
    try:
        payload = json.loads(listed.stdout)
        if isinstance(payload, dict):
            domain = payload.get("domain") or payload.get("host")
            if not domain and isinstance(payload.get("domains"), list) and payload["domains"]:
                d0 = payload["domains"][0]
                domain = d0.get("domain") if isinstance(d0, dict) else d0
        elif isinstance(payload, list) and payload:
            d0 = payload[0]
            domain = d0.get("domain") if isinstance(d0, dict) else d0
    except json.JSONDecodeError:
        pass
if not domain:
    created = run(["railway", "domain", "--service", os.environ["SERVICE_NAME"], "--json"])
    try:
        payload = json.loads(created.stdout)
        domain = (payload.get("domain") if isinstance(payload, dict) else None) or payload
    except json.JSONDecodeError:
        domain = created.stdout.strip()

if not domain or not isinstance(domain, str):
    print("Could not parse the public domain. Set WEBHOOK_URL in the Railway dashboard.", file=sys.stderr)
    raise SystemExit(1)

host = domain.replace("https://", "").replace("http://", "").split("/")[0]
webhook = f"https://{host}/"
run(["railway", "variable", "set",
     f"N8N_HOST={host}",
     f"WEBHOOK_URL={webhook}",
     "--service", os.environ["SERVICE_NAME"]])
print(f"n8n URL: {webhook}")
print("Next: open that URL, create the owner account, import n8n/meeting-notes-to-tasks.json")
PY

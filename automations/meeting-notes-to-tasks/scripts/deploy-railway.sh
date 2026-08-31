#!/usr/bin/env bash
# Create (if needed) and deploy n8n 1.123.75 on Railway from this folder.
# Requires: railway login OR RAILWAY_TOKEN, and N8N_ENCRYPTION_KEY.
#
# Order matters: volume + N8N_ENCRYPTION_KEY + WEBHOOK_URL must exist
# before the first n8n process starts. Rotating the encryption key later
# makes stored credentials unreadable.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.npm-global/bin:${PATH}"
PROJECT_NAME="${RAILWAY_PROJECT_NAME:-save5hours-n8n}"
SERVICE_NAME="${RAILWAY_SERVICE_NAME:-n8n}"
export PROJECT_NAME SERVICE_NAME
export RAILWAY_CALLER="${RAILWAY_CALLER:-skill:use-railway@1.3.7}"
export RAILWAY_AGENT_SESSION="${RAILWAY_AGENT_SESSION:-railway-skill-meeting-notes-3e35}"

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

def parse_domain(raw):
    if not raw or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        host = raw.strip().split()[0]
        return host or None
    domain = None
    if isinstance(payload, dict):
        domain = payload.get("domain") or payload.get("host")
        domains = payload.get("domains")
        if not domain and isinstance(domains, list) and domains:
            d0 = domains[0]
            domain = d0.get("domain") if isinstance(d0, dict) else d0
    elif isinstance(payload, list) and payload:
        d0 = payload[0]
        domain = d0.get("domain") if isinstance(d0, dict) else d0
    if isinstance(domain, str) and domain.strip():
        return domain.strip()
    return None

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

vol = run(
    [
        "railway",
        "volume",
        "add",
        "--service",
        service,
        "--mount-path",
        "/home/node/.n8n",
        "--json",
    ],
    check=False,
)
if vol.returncode != 0:
    print("volume add skipped (likely already attached):", vol.stderr.strip())

listed = run(
    ["railway", "domain", "list", "--service", service, "--json"],
    check=False,
)
domain = parse_domain(listed.stdout if listed.returncode == 0 else "")
if not domain:
    created = run(["railway", "domain", "--service", service, "--json"], check=False)
    domain = parse_domain(created.stdout)
    if not domain and created.returncode != 0:
        print("domain create deferred until after first deploy:", created.stderr.strip())

host = None
webhook = None
if domain:
    host = domain.replace("https://", "").replace("http://", "").split("/")[0]
    webhook = f"https://{host}/"

vars_cmd = [
    "railway", "variable", "set",
    f"N8N_ENCRYPTION_KEY={os.environ['N8N_ENCRYPTION_KEY']}",
    "N8N_PORT=${{PORT}}",
    "N8N_PROTOCOL=https",
    "GENERIC_TIMEZONE=Europe/Zurich",
    "N8N_DEFAULT_BINARY_DATA_MODE=filesystem",
    "N8N_PROXY_HOPS=1",
    "EXECUTIONS_DATA_PRUNE=true",
    "EXECUTIONS_DATA_MAX_AGE=168",
    "N8N_SECURE_COOKIE=true",
]
if host:
    vars_cmd.append(f"N8N_HOST={host}")
if webhook:
    vars_cmd.append(f"WEBHOOK_URL={webhook}")
vars_cmd.extend(["--service", service, "--skip-deploys"])
run(vars_cmd)

run([
    "railway", "up", "-y", "--ci", "--service", service,
    "-m", "n8n 1.123.75 meeting notes to HQ Tasks",
])

if not domain:
    created = run(["railway", "domain", "--service", service, "--json"])
    domain = parse_domain(created.stdout)
    if not domain:
        print("Could not parse the public domain. Set WEBHOOK_URL in the Railway dashboard.", file=sys.stderr)
        raise SystemExit(1)
    host = domain.replace("https://", "").replace("http://", "").split("/")[0]
    webhook = f"https://{host}/"
    run(["railway", "variable", "set",
         f"N8N_HOST={host}",
         f"WEBHOOK_URL={webhook}",
         "--service", service])

print(f"n8n URL: {webhook}")
print("Next: open that URL, create the owner account, add Google/Notion/OpenRouter credentials in the n8n UI.")
print("The meeting-notes workflow is imported on first boot (inactive until you activate it).")
PY

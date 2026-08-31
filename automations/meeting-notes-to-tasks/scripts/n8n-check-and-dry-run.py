#!/usr/bin/env python3
"""Inspect live n8n (no secret values) and dry-run notes → HQ Tasks when ready.

Exit codes:
  0  dry-run posted (or --status-only and instance is healthy)
  2  waiting on Notion token / inactive workflow
  1  error
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "paella-notes.txt"
N8N_URL = "https://n8n-production-192e.up.railway.app"
WEBHOOK_PATH = "/webhook/meeting-notes"
WF_ID = "KfrQb6c79aJPPxYE"
SERVICE = "n8n"
ENV = "production"

# Single line: railway ssh + node -e cannot take embedded newlines.
INSPECT_JS = (
    'const {DatabaseSync}=require("node:sqlite");const fs=require("fs");'
    'const p="/home/node/.n8n/database.sqlite";'
    'const out={db_exists:fs.existsSync(p),uid:process.getuid(),credentials:[],workflows:[]};'
    'if(fs.existsSync(p)){const db=new DatabaseSync(p,{readOnly:true});'
    'out.credentials=db.prepare("SELECT id, name, type FROM credentials_entity ORDER BY name").all();'
    'out.workflows=db.prepare("SELECT id, name, active FROM workflow_entity").all();}'
    'process.stdout.write(JSON.stringify(out));'
)


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], *, timeout: int = 60, secret: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("RAILWAY_CALLER", "skill:use-railway@1.3.7")
    shown = [a if not secret else "[redacted]" for a in cmd]
    log("+ " + " ".join(shown))
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


def railway_vars() -> dict[str, str]:
    proc = run(
        ["railway", "variables", "--service", SERVICE, "--environment", ENV, "--json"],
        timeout=45,
    )
    if proc.returncode != 0:
        raise SystemExit(f"railway variables failed: {(proc.stderr or proc.stdout)[:400]}")
    data = json.loads(proc.stdout)
    if not isinstance(data, dict):
        raise SystemExit("railway variables: unexpected JSON")
    return {str(k): str(v) if v is not None else "" for k, v in data.items()}


def present(vars_: dict[str, str], key: str) -> bool:
    return bool(vars_.get(key, "").strip())


def inspect_sqlite() -> dict:
    proc = run(
        [
            "railway",
            "ssh",
            "--service",
            SERVICE,
            "--environment",
            ENV,
            "--",
            f"node -e {json.dumps(INSPECT_JS)}",
        ],
        timeout=90,
    )
    if proc.returncode != 0:
        raise SystemExit(f"railway ssh inspect failed: {(proc.stderr or proc.stdout)[:500]}")
    text = proc.stdout.strip()
    # Railway may append deprecation warnings after JSON
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise SystemExit(f"inspect: no JSON in ssh output ({text[:200]!r})")
    return json.loads(text[start : end + 1])


def cred_ids(info: dict) -> set[str]:
    return {str(row.get("id") or "") for row in info.get("credentials") or []}


def workflow_active(info: dict) -> bool:
    for row in info.get("workflows") or []:
        if str(row.get("id")) == WF_ID:
            return bool(row.get("active"))
    return False


def print_status(vars_: dict[str, str], info: dict) -> None:
    ids = cred_ids(info)
    log("n8n status (secrets redacted)")
    log(f"  url: {N8N_URL}/")
    log(f"  sqlite credentials: {sorted(ids) or '(none)'}")
    log(f"  workflow {WF_ID} active: {workflow_active(info)}")
    for key in (
        "OPENROUTER_API_KEY",
        "NOTION_API_KEY",
        "N8N_WEBHOOK_SECRET",
        "GEMINI_NOTES_FOLDER_ID",
        "GOOGLE_OAUTH_CLIENT_ID",
        "N8N_ACTIVATE_WORKFLOW",
        "N8N_CLEAR_LICENSE",
    ):
        val = vars_.get(key, "")
        if key in ("N8N_ACTIVATE_WORKFLOW", "N8N_CLEAR_LICENSE") and val.strip():
            log(f"  railway {key}: {val.strip()}")
        else:
            log(f"  railway {key}: {'yes' if val.strip() else 'NO'}")


def activate_via_ssh() -> None:
    cmd = (
        "if command -v gosu >/dev/null 2>&1; then "
        "exec gosu node env HOME=/home/node N8N_USER_FOLDER=/home/node/.n8n "
        f"n8n update:workflow --id {WF_ID} --active true; "
        "else echo NO_GOSU; exit 1; fi"
    )
    proc = run(
        ["railway", "ssh", "--service", SERVICE, "--environment", ENV, "--", cmd],
        timeout=120,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    log(out[-800:] if out else "(no ssh output)")
    if proc.returncode != 0:
        raise SystemExit("failed to activate workflow over ssh")


def ensure_activate_var() -> None:
    proc = run(
        [
            "railway",
            "variable",
            "set",
            "--service",
            SERVICE,
            "--environment",
            ENV,
            "N8N_ACTIVATE_WORKFLOW=true",
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(f"failed to set N8N_ACTIVATE_WORKFLOW: {(proc.stderr or proc.stdout)[:400]}")


def redeploy() -> None:
    proc = run(
        ["railway", "redeploy", "--service", SERVICE, "--environment", ENV, "--yes"],
        timeout=90,
    )
    if proc.returncode != 0:
        log("redeploy CLI failed; trying railway up")
        proc = run(
            ["railway", "up", "-y", "--ci", "--service", SERVICE],
            timeout=180,
        )
        if proc.returncode != 0:
            raise SystemExit(f"redeploy failed: {(proc.stderr or proc.stdout)[:400]}")
    log("waiting for healthz after redeploy")
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{N8N_URL}/healthz", timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200 and "ok" in body.lower():
                    log("healthz ok")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(5)
    raise SystemExit("n8n did not become healthy after redeploy")


def post_dry_run(secret: str) -> int:
    notes = FIXTURE.read_text(encoding="utf-8")
    payload = json.dumps(
        {
            "name": "Gemini notes — team lunch (n8n dry-run)",
            "text": notes,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{N8N_URL}{WEBHOOK_PATH}",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Secret": secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:500]
            log(f"dry-run HTTP {resp.status}: {body}")
            return 0
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")[:500]
        log(f"dry-run HTTP {err.code}: {body}")
        return 2 if err.code in (403, 404) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Print redacted status and exit (do not activate or POST).",
    )
    args = parser.parse_args()

    vars_ = railway_vars()
    info = inspect_sqlite()
    print_status(vars_, info)

    ids = cred_ids(info)
    has_or = "OPENROUTER" in ids or present(vars_, "OPENROUTER_API_KEY")
    has_notion_sqlite = "NOTION" in ids
    has_notion_railway = present(vars_, "NOTION_API_KEY")
    has_webhook = "WEBHOOK_SECRET" in ids or present(vars_, "N8N_WEBHOOK_SECRET")
    active = workflow_active(info)

    if args.status_only:
        if has_or and has_webhook and (has_notion_sqlite or has_notion_railway) and active:
            return 0
        return 2

    if not has_or:
        log("blocked: OpenRouter credential missing")
        return 1
    if not has_webhook:
        log("blocked: webhook secret missing")
        return 1

    if has_notion_railway and not has_notion_sqlite:
        log("Railway has NOTION_API_KEY; sqlite does not — activating + redeploy so provision writes it")
        ensure_activate_var()
        redeploy()
        info = inspect_sqlite()
        print_status(railway_vars(), info)
        ids = cred_ids(info)
        has_notion_sqlite = "NOTION" in ids
        active = workflow_active(info)

    if not has_notion_sqlite:
        log(
            "blocked: Notion internal integration token is missing. "
            "Create Save 5 Hours n8n at https://www.notion.so/my-integrations "
            "connect it to HQ Tasks, then paste NOTION_API_KEY on Railway n8n "
            "or in the n8n Credentials UI as 'Notion (Save 5 Hours HQ)'."
        )
        return 2

    if not active:
        log("Notion credential is present; activating workflow")
        if not present(vars_, "N8N_ACTIVATE_WORKFLOW"):
            ensure_activate_var()
        activate_via_ssh()
        info = inspect_sqlite()
        active = workflow_active(info)
        log(f"workflow active after ssh: {active}")
        if not active:
            log("ssh activate did not flip active; redeploying with N8N_ACTIVATE_WORKFLOW=true")
            redeploy()
            info = inspect_sqlite()
            active = workflow_active(info)
        if not active:
            log("blocked: workflow still inactive")
            return 2

    secret = vars_.get("N8N_WEBHOOK_SECRET", "").strip()
    if not secret:
        log("blocked: cannot POST dry-run without N8N_WEBHOOK_SECRET in Railway")
        return 2

    log("posting paella fixture to webhook (inline text, no Drive OAuth)")
    return post_dry_run(secret)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

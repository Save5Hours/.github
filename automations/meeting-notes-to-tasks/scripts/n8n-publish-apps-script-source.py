#!/usr/bin/env python3
"""Publish a GET webhook that returns the Apps Script source (no secrets).

Live URL: https://n8n-production-192e.up.railway.app/webhook/apps-script-source
Does not touch the Meeting notes → HQ Tasks workflow.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apps-script-drive-webhook.js"
ENV_CANDIDATES = [Path("/workspace/.env"), ROOT / ".env"]
WF_NAME = "Apps Script source (Drive setup)"
N8N_URL = "https://n8n-production-192e.up.railway.app"


def load_dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in ENV_CANDIDATES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def request(api_key: str, method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"X-N8N-API-KEY": api_key, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(N8N_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"message": raw}
        except json.JSONDecodeError:
            parsed = {"message": raw[:400]}
        print(f"{method} {path} -> {err.code} {json.dumps(parsed)[:300]}", flush=True)
        return err.code, parsed


def workflow_payload(source: str) -> dict:
    return {
        "name": WF_NAME,
        "nodes": [
            {
                "id": "apps-script-source",
                "name": "Apps Script source",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "webhookId": "apps-script-source",
                "parameters": {
                    "httpMethod": "GET",
                    "path": "apps-script-source",
                    "responseMode": "onReceived",
                    "options": {
                        "responseData": source,
                        "responseHeaders": {
                            "entries": [
                                {
                                    "name": "Content-Type",
                                    "value": "text/plain; charset=utf-8",
                                },
                            ]
                        },
                    },
                },
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }


def main() -> int:
    env = load_dotenv()
    api_key = env.get("N8N_API_KEY") or os.environ.get("N8N_API_KEY") or ""
    if not api_key:
        print("blocked: N8N_API_KEY missing")
        return 1
    source = SCRIPT.read_text(encoding="utf-8")
    if "function verifyDrivePath(" not in source:
        print("blocked: Apps Script source missing verifyDrivePath")
        return 1
    if "WEBHOOK_SECRET_PASTE" not in source:
        print("blocked: Apps Script source missing WEBHOOK_SECRET_PASTE")
        return 1
    payload = workflow_payload(source)
    code, listed = request(api_key, "GET", "/api/v1/workflows")
    workflows = listed.get("data") if isinstance(listed, dict) else []
    existing = next((w for w in (workflows or []) if w.get("name") == WF_NAME), None)
    if existing:
        wf_id = existing["id"]
        code, body = request(api_key, "PUT", f"/api/v1/workflows/{wf_id}", payload)
        print(f"update {wf_id} status={code}")
    else:
        code, body = request(api_key, "POST", "/api/v1/workflows", payload)
        print(f"create status={code}")
        if not isinstance(body, dict) or not body.get("id"):
            return 1
        wf_id = body["id"]
    code, body = request(api_key, "POST", f"/api/v1/workflows/{wf_id}/activate")
    print(f"activate status={code} active={body.get('active') if isinstance(body, dict) else None}")
    if code not in (200, 201):
        return 1
    req = urllib.request.Request(f"{N8N_URL}/webhook/apps-script-source", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8", errors="replace")
        print(f"GET webhook HTTP {resp.status} bytes={len(text)}")
        if "function verifyDrivePath(" not in text:
            print("blocked: webhook body is not the Apps Script")
            return 1
    print("apps-script-source webhook is live")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

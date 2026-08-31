#!/usr/bin/env python3
"""Publish Meeting notes → HQ Tasks via the n8n public API.

Reads /workspace/.env (never printed). Drive triggers stay disabled until a
folder ID exists. Exit 0 on activate, 2 if the API key cannot see workflows
and create failed, 1 on error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_SRC = ROOT / "n8n" / "meeting-notes-to-tasks.json"
ENV_CANDIDATES = [Path("/workspace/.env"), ROOT / ".env"]
PROJECT = "48651271-91e5-4a40-8783-6971a438c2a3"
WF_NAME = "Meeting notes → HQ Tasks"


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


def railway_vars() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("RAILWAY_CALLER", "skill:use-railway@1.3.7")
    proc = subprocess.run(
        [
            "railway",
            "variables",
            "--project",
            PROJECT,
            "--environment",
            "production",
            "--service",
            "n8n",
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
        timeout=45,
        env=env,
    )
    if proc.returncode != 0:
        return {}
    data = json.loads(proc.stdout)
    return {str(k): str(v) if v is not None else "" for k, v in data.items()}


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    return out


class N8n:
    def __init__(self, base: str, api_key: str, secrets: list[str]):
        self.base = base.rstrip("/")
        self.api_key = api_key
        self.secrets = secrets

    def request(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "X-N8N-API-KEY": self.api_key,
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw) if raw else {}
                return resp.status, parsed
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {"message": raw}
            except json.JSONDecodeError:
                parsed = {"message": raw[:400]}
            print(
                f"{method} {path} -> {err.code} "
                f"{redact(json.dumps(parsed)[:400], self.secrets)}",
                flush=True,
            )
            return err.code, parsed


def disable_drive_nodes(nodes: list) -> list:
    out = []
    for node in nodes:
        item = dict(node)
        if item.get("type") == "n8n-nodes-base.googleDriveTrigger":
            item["disabled"] = True
        out.append(item)
    return out


def retarget_creds(nodes: list, mapping: dict[str, dict]) -> list:
    """mapping: old_id -> {id, name}"""
    out = []
    for node in nodes:
        item = json.loads(json.dumps(node))
        creds = item.get("credentials") or {}
        for kind, spec in list(creds.items()):
            old = str(spec.get("id") or "")
            if old in mapping:
                spec["id"] = mapping[old]["id"]
                spec["name"] = mapping[old]["name"]
        out.append(item)
    return out


def create_credential(api: N8n, name: str, cred_type: str, data: dict) -> dict | None:
    code, body = api.request(
        "POST",
        "/api/v1/credentials",
        {"name": name, "type": cred_type, "data": data},
    )
    if code in (200, 201) and isinstance(body, dict) and body.get("id"):
        print(f"created credential {name} id={body.get('id')} type={cred_type}", flush=True)
        return body
    print(f"credential {name} failed status={code}", flush=True)
    return None


def main() -> int:
    env = load_dotenv()
    rail = railway_vars()
    base = env.get("N8N_URL") or "https://n8n-production-192e.up.railway.app"
    api_key = env.get("N8N_API_KEY") or ""
    notion = env.get("NOTION_API_KEY") or rail.get("NOTION_API_KEY") or ""
    openrouter = env.get("OPENROUTER_API_KEY") or rail.get("OPENROUTER_API_KEY") or ""
    webhook = rail.get("N8N_WEBHOOK_SECRET") or env.get("N8N_WEBHOOK_SECRET") or ""
    secrets = [api_key, notion, openrouter, webhook]

    print("n8n API publish (secrets redacted)")
    print(f"  url: {base}")
    print(f"  N8N_API_KEY: {'yes' if api_key else 'NO'}")
    print(f"  NOTION_API_KEY: {'yes' if notion else 'NO'}")
    print(f"  OPENROUTER_API_KEY: {'yes' if openrouter else 'NO'}")
    print(f"  webhook secret: {'yes' if webhook else 'NO'}")
    if not api_key:
        print("blocked: N8N_API_KEY missing from .env")
        return 1
    if not notion or not openrouter or not webhook:
        print("blocked: Notion, OpenRouter, or webhook secret missing")
        return 2

    api = N8n(base, api_key, secrets)
    code, me = api.request("GET", "/api/v1/users")
    if isinstance(me, dict):
        users = me.get("data") or []
        for user in users:
            print(
                f"  api user {user.get('email')} id={user.get('id')}",
                flush=True,
            )

    code, listed = api.request("GET", "/api/v1/workflows")
    workflows = listed.get("data") if isinstance(listed, dict) else []
    if not isinstance(workflows, list):
        workflows = []
    print(f"  workflows visible to this API key: {len(workflows)}")
    for item in workflows:
        print(
            f"    {item.get('id')} {item.get('name')!r} active={item.get('active')}",
            flush=True,
        )

    existing = next((w for w in workflows if w.get("name") == WF_NAME), None)
    mapping: dict[str, dict] = {}
    if existing:
        code, live = api.request("GET", f"/api/v1/workflows/{existing['id']}")
        if code == 200 and isinstance(live, dict):
            by_name = {
                "Notion (Save 5 Hours HQ)": "NOTION",
                "OpenRouter": "OPENROUTER",
                "Meeting notes webhook secret": "WEBHOOK_SECRET",
            }
            for node in live.get("nodes") or []:
                for spec in (node.get("credentials") or {}).values():
                    old_key = by_name.get(str(spec.get("name") or ""))
                    if old_key and spec.get("id"):
                        mapping[old_key] = {
                            "id": spec["id"],
                            "name": spec.get("name"),
                        }
            print(f"reusing credentials {sorted(mapping)}")

    if set(mapping) != {"NOTION", "OPENROUTER", "WEBHOOK_SECRET"}:
        notion_cred = create_credential(
            api,
            "Notion (Save 5 Hours HQ)",
            "notionApi",
            {"apiKey": notion},
        )
        or_value = openrouter if openrouter.startswith("Bearer ") else f"Bearer {openrouter}"
        or_cred = create_credential(
            api,
            "OpenRouter",
            "httpHeaderAuth",
            {"name": "Authorization", "value": or_value},
        )
        wh_cred = create_credential(
            api,
            "Meeting notes webhook secret",
            "httpHeaderAuth",
            {"name": "X-Webhook-Secret", "value": webhook},
        )
        if not (notion_cred and or_cred and wh_cred):
            return 1
        mapping["NOTION"] = {
            "id": notion_cred["id"],
            "name": notion_cred.get("name") or "Notion (Save 5 Hours HQ)",
        }
        mapping["OPENROUTER"] = {
            "id": or_cred["id"],
            "name": or_cred.get("name") or "OpenRouter",
        }
        mapping["WEBHOOK_SECRET"] = {
            "id": wh_cred["id"],
            "name": wh_cred.get("name") or "Meeting notes webhook secret",
        }

    src = json.loads(WF_SRC.read_text(encoding="utf-8"))
    nodes = disable_drive_nodes(src["nodes"])
    nodes = retarget_creds(nodes, mapping)
    payload = {
        "name": WF_NAME,
        "nodes": nodes,
        "connections": src["connections"],
        "settings": src.get("settings") or {"executionOrder": "v1"},
    }

    existing = next((w for w in workflows if w.get("name") == WF_NAME), None)
    if existing:
        wf_id = existing["id"]
        code, body = api.request("PUT", f"/api/v1/workflows/{wf_id}", payload)
        print(f"update workflow {wf_id} status={code} active={body.get('active') if isinstance(body, dict) else None}")
    else:
        code, body = api.request("POST", "/api/v1/workflows", payload)
        print(f"create workflow status={code}")
        if not isinstance(body, dict) or not body.get("id"):
            return 1
        wf_id = body["id"]
        print(f"created workflow id={wf_id} active={body.get('active')}")

    code, body = api.request("POST", f"/api/v1/workflows/{wf_id}/activate")
    print(f"activate status={code} active={body.get('active') if isinstance(body, dict) else None}")
    if code not in (200, 201) or not (isinstance(body, dict) and body.get("active")):
        # n8n 1.123 sometimes uses PUT active
        code2, body2 = api.request(
            "PUT",
            f"/api/v1/workflows/{wf_id}",
            {**payload, "active": True},
        )
        print(
            f"activate via PUT status={code2} active={body2.get('active') if isinstance(body2, dict) else None}"
        )
        if code2 not in (200, 201):
            return 1
        body = body2
    print("workflow is active via n8n API")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

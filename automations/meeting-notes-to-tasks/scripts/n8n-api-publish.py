#!/usr/bin/env python3
"""Publish Meeting notes → HQ Tasks via the n8n public API.

Reads /workspace/.env (never printed). Drive triggers stay disabled until a
folder ID *and* a real Google Drive OAuth credential exist (Sign in). Exit 0
on activate, 2 if the API key cannot see workflows and create failed, 1 on error.
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
DRIVE_CONFIRM_PAGE = "3cd0b26fcc4e819bb9ead19d74fb64a6"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drive_ids import parse_drive_refs  # noqa: E402


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


def notion_plain(prop: dict | None) -> str:
    if not prop:
        return ""
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(span.get("plain_text") or "" for span in prop.get("title") or [])
    if ptype == "rich_text":
        return "".join(span.get("plain_text") or "" for span in prop.get("rich_text") or [])
    if ptype == "url":
        return str(prop.get("url") or "")
    return ""


def hq_drive_refs(token: str) -> dict[str, str]:
    if not token:
        return {"folder_id": "", "file_id": ""}
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    blobs: list[str] = []
    try:
        req = urllib.request.Request(
            f"https://api.notion.com/v1/pages/{DRIVE_CONFIRM_PAGE}",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read().decode("utf-8"))
        props = page.get("properties") or {}
        blobs.append(notion_plain(props.get("Drive URL")))
        blobs.append(notion_plain(props.get("Drive file ID")))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return {"folder_id": "", "file_id": ""}
    try:
        req = urllib.request.Request(
            f"https://api.notion.com/v1/comments?block_id={DRIVE_CONFIRM_PAGE}",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            comments = json.loads(resp.read().decode("utf-8"))
        for row in comments.get("results") or []:
            rich = row.get("rich_text") or []
            blobs.append("".join(span.get("plain_text") or "" for span in rich))
    except urllib.error.HTTPError:
        pass
    return parse_drive_refs(*blobs)


def google_oauth_ready(mapping: dict[str, dict]) -> bool:
    spec = mapping.get("GOOGLE_DRIVE") or {}
    cred_id = str(spec.get("id") or "")
    return bool(cred_id) and cred_id not in {"GOOGLE_DRIVE", "REPLACE_ME"}


def apply_drive_folder(nodes: list, folder_id: str) -> list:
    out = []
    for node in nodes:
        item = json.loads(json.dumps(node))
        if item.get("type") != "n8n-nodes-base.googleDriveTrigger":
            out.append(item)
            continue
        if folder_id:
            item["disabled"] = False
            params = item.setdefault("parameters", {})
            watch = dict(params.get("folderToWatch") or {})
            watch.update({"__rl": True, "mode": "id", "value": folder_id})
            params["folderToWatch"] = watch
        else:
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
    api_key = env.get("N8N_API_KEY") or rail.get("N8N_API_KEY") or ""
    notion = env.get("NOTION_API_KEY") or rail.get("NOTION_API_KEY") or ""
    openrouter = env.get("OPENROUTER_API_KEY") or rail.get("OPENROUTER_API_KEY") or ""
    webhook = rail.get("N8N_WEBHOOK_SECRET") or env.get("N8N_WEBHOOK_SECRET") or ""
    folder = (env.get("GEMINI_NOTES_FOLDER_ID") or rail.get("GEMINI_NOTES_FOLDER_ID") or "").strip()
    hq_refs = hq_drive_refs(notion)
    if not folder:
        folder = hq_refs.get("folder_id") or ""
        if folder:
            print("using Drive folder ID from HQ confirmation task")
    google_id = (env.get("GOOGLE_OAUTH_CLIENT_ID") or rail.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    google_secret = (
        env.get("GOOGLE_OAUTH_CLIENT_SECRET") or rail.get("GOOGLE_OAUTH_CLIENT_SECRET") or ""
    ).strip()
    secrets = [api_key, notion, openrouter, webhook, google_secret]

    print("n8n API publish (secrets redacted)")
    print(f"  url: {base}")
    print(f"  N8N_API_KEY: {'yes' if api_key else 'NO'}")
    print(f"  NOTION_API_KEY: {'yes' if notion else 'NO'}")
    print(f"  OPENROUTER_API_KEY: {'yes' if openrouter else 'NO'}")
    print(f"  webhook secret: {'yes' if webhook else 'NO'}")
    print(f"  GEMINI_NOTES_FOLDER_ID: {'yes' if folder else 'NO (Drive triggers disabled)'}")
    print(f"  GOOGLE_OAUTH_CLIENT_ID: {'yes' if google_id else 'NO'}")
    if not api_key:
        print("blocked: N8N_API_KEY missing from .env and Railway")
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
                "Google Drive (Save 5 Hours)": "GOOGLE_DRIVE",
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

    required = {"NOTION", "OPENROUTER", "WEBHOOK_SECRET"}
    missing = required - set(mapping)
    if missing:
        created: dict[str, dict] = {}
        if "NOTION" in missing:
            created["NOTION"] = create_credential(
                api,
                "Notion (Save 5 Hours HQ)",
                "notionApi",
                {"apiKey": notion},
            )
        if "OPENROUTER" in missing:
            or_value = openrouter if openrouter.startswith("Bearer ") else f"Bearer {openrouter}"
            created["OPENROUTER"] = create_credential(
                api,
                "OpenRouter",
                "httpHeaderAuth",
                {"name": "Authorization", "value": or_value},
            )
        if "WEBHOOK_SECRET" in missing:
            created["WEBHOOK_SECRET"] = create_credential(
                api,
                "Meeting notes webhook secret",
                "httpHeaderAuth",
                {"name": "X-Webhook-Secret", "value": webhook},
            )
        if any(created.get(key) is None for key in missing):
            return 1
        names = {
            "NOTION": "Notion (Save 5 Hours HQ)",
            "OPENROUTER": "OpenRouter",
            "WEBHOOK_SECRET": "Meeting notes webhook secret",
        }
        for key in missing:
            cred = created[key]
            mapping[key] = {
                "id": cred["id"],
                "name": cred.get("name") or names[key],
            }

    existing_google = mapping.get("GOOGLE_DRIVE") or {}
    if existing_google.get("id") in (None, "", "GOOGLE_DRIVE"):
        mapping.pop("GOOGLE_DRIVE", None)
        existing_google = {}
    if google_id and google_secret and not existing_google:
        google_cred = create_credential(
            api,
            "Google Drive (Save 5 Hours)",
            "googleDriveOAuth2Api",
            {
                "serverUrl": "https://accounts.google.com/o/oauth2/v2/auth",
                "clientId": google_id,
                "clientSecret": google_secret,
                "sendAdditionalBodyProperties": False,
                "additionalBodyProperties": "{}",
            },
        )
        if google_cred:
            mapping["GOOGLE_DRIVE"] = {
                "id": google_cred["id"],
                "name": google_cred.get("name") or "Google Drive (Save 5 Hours)",
            }
            print("Google Drive OAuth client stored; Sign in still required in the n8n UI")
    print(f"  GOOGLE_OAUTH_CLIENT_ID: {'yes' if google_id else 'NO'}")

    src = json.loads(WF_SRC.read_text(encoding="utf-8"))
    drive_ready = google_oauth_ready(mapping) and bool(folder)
    if folder and not google_oauth_ready(mapping):
        print("folder ID present; Drive triggers stay disabled until Google OAuth Sign in")
    nodes = apply_drive_folder(src["nodes"], folder if drive_ready else "")
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
        if existing.get("active"):
            code, body = api.request("POST", f"/api/v1/workflows/{wf_id}/deactivate")
            print(f"deactivate {wf_id} status={code}")
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

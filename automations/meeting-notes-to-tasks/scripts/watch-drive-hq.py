#!/usr/bin/env python3
"""List HQ Tasks with Origin=Meeting and report Drive file IDs.

Exit 0 if at least one row has a real Google Drive file id (not inline-*).
Exit 2 if only webhook dry-runs (inline-*) or empty ids exist.
Exit 1 on API errors.

--advance also reads the Drive confirmation task, n8n executions, and will
POST a publicly exportable Doc to the webhook (never the paella fixture).

Reads NOTION_API_KEY from /workspace/.env or the environment. Never prints secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drive_ids import export_url, is_real_drive_id, parse_drive_refs  # noqa: E402

TASKS_DB = "3bc0b26fcc4e8057b7ade1cdf5a67e6e"
DRIVE_CONFIRM_PAGE = "3cd0b26fcc4e819bb9ead19d74fb64a6"
N8N_URL = "https://n8n-production-192e.up.railway.app"
WEBHOOK_PATH = "/webhook/meeting-notes"
MEETING_WF_ID = "9JlE8lA1TQdlxw0S"
PROJECT = "48651271-91e5-4a40-8783-6971a438c2a3"
SERVICE = "n8n"
ENV = "production"
ENV_CANDIDATES = [Path("/workspace/.env"), Path(__file__).resolve().parents[1] / ".env"]


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


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def notion_query(token: str) -> list[dict]:
    body = json.dumps(
        {
            "filter": {"property": "Origin", "select": {"equals": "Meeting"}},
            "page_size": 100,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{TASKS_DB}/query",
        data=body,
        method="POST",
        headers=notion_headers(token),
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("results") or [])


def plain(prop: dict | None) -> str:
    if not prop:
        return ""
    if prop.get("type") == "title":
        return "".join(span.get("plain_text") or "" for span in prop.get("title") or [])
    if prop.get("type") == "rich_text":
        return "".join(span.get("plain_text") or "" for span in prop.get("rich_text") or [])
    if prop.get("type") == "url":
        return str(prop.get("url") or "")
    return ""


def hq_confirm_refs(token: str) -> dict[str, str]:
    blobs: list[str] = []
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{DRIVE_CONFIRM_PAGE}",
        headers=notion_headers(token),
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = json.loads(resp.read().decode("utf-8"))
    props = page.get("properties") or {}
    blobs.append(plain(props.get("Drive URL")))
    blobs.append(plain(props.get("Drive file ID")))
    try:
        req = urllib.request.Request(
            f"https://api.notion.com/v1/comments?block_id={DRIVE_CONFIRM_PAGE}",
            headers=notion_headers(token),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            comments = json.loads(resp.read().decode("utf-8"))
        for row in comments.get("results") or []:
            rich = row.get("rich_text") or []
            blobs.append("".join(span.get("plain_text") or "" for span in rich))
    except urllib.error.HTTPError:
        pass
    refs = parse_drive_refs(*blobs)
    refs["drive_url"] = plain(props.get("Drive URL"))
    refs["drive_file_id_prop"] = plain(props.get("Drive file ID"))
    return refs


def n8n_executions(api_key: str) -> list[dict]:
    req = urllib.request.Request(
        f"{N8N_URL}/api/v1/executions?limit=50&workflowId={MEETING_WF_ID}",
        headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("data") or [])


def railway_webhook_secret() -> str:
    env = os.environ.copy()
    env.setdefault("RAILWAY_CALLER", "skill:use-railway@1.3.7")
    proc = subprocess.run(
        [
            "railway",
            "variables",
            "--project",
            PROJECT,
            "--environment",
            ENV,
            "--service",
            SERVICE,
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
        timeout=45,
        env=env,
    )
    if proc.returncode != 0:
        return ""
    data = json.loads(proc.stdout)
    if not isinstance(data, dict):
        return ""
    return str(data.get("N8N_WEBHOOK_SECRET") or "").strip()


def try_export_and_post(file_id: str, secret: str) -> bool:
    url = export_url(file_id)
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=45) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        print(f"public export HTTP {err.code} for Drive file (not shared)")
        return False
    compact = " ".join(text.split())
    if len(compact) < 80:
        print(f"public export too short ({len(compact)} chars)")
        return False
    payload = json.dumps(
        {
            "fileId": file_id,
            "name": "Gemini notes — Drive path verification (n8n)",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
            "text": text,
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
            print(f"posted public Drive doc to webhook HTTP {resp.status}")
            return resp.status < 300
    except urllib.error.HTTPError as err:
        print(f"webhook POST HTTP {err.code}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--advance",
        action="store_true",
        help="Read HQ Drive confirmation + n8n executions; POST public docs only.",
    )
    args = parser.parse_args()

    env = load_dotenv()
    token = os.environ.get("NOTION_API_KEY") or env.get("NOTION_API_KEY") or ""
    api_key = os.environ.get("N8N_API_KEY") or env.get("N8N_API_KEY") or ""
    if not token:
        print("blocked: NOTION_API_KEY missing")
        return 1
    try:
        rows = notion_query(token)
    except urllib.error.HTTPError as err:
        print(f"notion HTTP {err.code}")
        return 1

    real = 0
    inline = 0
    empty = 0
    real_ids: set[str] = set()
    print("HQ Tasks Origin=Meeting")
    for page in rows:
        props = page.get("properties") or {}
        name = plain(props.get("Name"))
        file_id = plain(props.get("Drive file ID"))
        url = plain(props.get("Drive URL"))
        page_url = page.get("url") or ""
        kind = "real" if is_real_drive_id(file_id) else ("inline" if file_id.startswith("inline-") else "empty")
        if kind == "real":
            real += 1
            real_ids.add(file_id.strip())
        elif kind == "inline":
            inline += 1
        else:
            empty += 1
        print(f"  [{kind}] {name!r} drive={file_id or '-'} url={url or '-'} page={page_url}")
    print(f"counts real={real} inline={inline} empty={empty} total={len(rows)}")

    if args.advance:
        try:
            refs = hq_confirm_refs(token)
        except urllib.error.HTTPError as err:
            print(f"confirm task HTTP {err.code}")
            refs = {"folder_id": "", "file_id": ""}
        print(
            "HQ Drive confirmation "
            f"folder={refs.get('folder_id') or '-'} file={refs.get('file_id') or '-'} "
            f"url={refs.get('drive_url') or '-'}"
        )
        if api_key:
            try:
                executions = n8n_executions(api_key)
            except urllib.error.HTTPError as err:
                print(f"n8n executions HTTP {err.code}")
                executions = []
            notes = [e for e in executions if e.get("workflowId") == MEETING_WF_ID]
            ok = [e for e in notes if e.get("status") == "success"]
            print(
                f"n8n meeting-notes executions {len(notes)} "
                f"success={len(ok)} (api {len(executions)})"
            )
            for item in notes[:12]:
                print(
                    f"  id={item.get('id')} status={item.get('status')} "
                    f"mode={item.get('mode')} start={item.get('startedAt')}"
                )
        confirm_file = refs.get("file_id") or ""
        if confirm_file and confirm_file not in real_ids:
            secret = railway_webhook_secret()
            if secret:
                print("trying public Google Doc export for HQ file ID")
                try_export_and_post(confirm_file, secret)
            else:
                print("no Railway webhook secret; skip public export POST")

    return 0 if real else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

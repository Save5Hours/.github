#!/usr/bin/env python3
"""List HQ Tasks with Origin=Meeting and report Drive file IDs.

Exit 0 if at least one row has a real Google Drive file id (not inline-*).
Exit 2 if only webhook dry-runs (inline-*) or empty ids exist.
Exit 1 on API errors.

Reads NOTION_API_KEY from /workspace/.env or the environment. Never prints secrets.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TASKS_DB = "3bc0b26fcc4e8057b7ade1cdf5a67e6e"
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
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
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


def is_real_drive_id(file_id: str) -> bool:
    value = file_id.strip()
    return bool(value) and not value.startswith("inline-")


def main() -> int:
    env = load_dotenv()
    token = os.environ.get("NOTION_API_KEY") or env.get("NOTION_API_KEY") or ""
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
        elif kind == "inline":
            inline += 1
        else:
            empty += 1
        print(f"  [{kind}] {name!r} drive={file_id or '-'} url={url or '-'} page={page_url}")
    print(f"counts real={real} inline={inline} empty={empty} total={len(rows)}")
    return 0 if real else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

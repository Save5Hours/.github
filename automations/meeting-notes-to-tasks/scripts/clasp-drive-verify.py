#!/usr/bin/env python3
"""Create a real Google Doc via clasp OAuth and POST it to n8n.

Uses ~/.clasprc.json (drive.file). Does not print tokens or the webhook secret.
Exit 0 after a successful n8n POST, 2 if clasp is not logged in, 1 on error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "fixtures" / "drive-verify-notes.txt"
N8N_URL = "https://n8n-production-192e.up.railway.app/webhook/meeting-notes"
PROJECT = "48651271-91e5-4a40-8783-6971a438c2a3"
CLASPRC_CANDIDATES = [
    Path.home() / ".clasprc.json",
    Path.home() / ".config" / "clasp" / ".clasprc.json",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_UPLOAD = (
    "https://www.googleapis.com/upload/drive/v3/files"
    "?uploadType=multipart&fields=id,name,webViewLink,mimeType"
)


def load_dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in (Path("/workspace/.env"), ROOT / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_clasprc() -> dict:
    for path in CLASPRC_CANDIDATES:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def token_blob(clasprc: dict) -> dict:
    if isinstance(clasprc.get("token"), dict):
        return clasprc["token"]
    tokens = clasprc.get("tokens")
    if isinstance(tokens, dict):
        for key in ("default", "clasprc"):
            if isinstance(tokens.get(key), dict):
                return tokens[key]
        for value in tokens.values():
            if isinstance(value, dict) and value.get("access_token"):
                return value
    return {}


def access_token(clasprc: dict) -> str:
    blob = token_blob(clasprc)
    token = str(blob.get("access_token") or "").strip()
    expiry = blob.get("expiry_date") or blob.get("expiry") or 0
    try:
        expiry_ms = float(expiry)
    except (TypeError, ValueError):
        expiry_ms = 0
    fresh = token and (not expiry_ms or expiry_ms > time.time() * 1000 + 30_000)
    if fresh:
        return token
    refresh = str(blob.get("refresh_token") or "").strip()
    client_id = str(clasprc.get("client_id") or blob.get("client_id") or "").strip()
    client_secret = str(
        clasprc.get("client_secret") or blob.get("client_secret") or ""
    ).strip()
    if not (refresh and client_id and client_secret):
        return token
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("access_token") or "").strip()


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
        return ""
    data = json.loads(proc.stdout)
    return str(data.get("N8N_WEBHOOK_SECRET") or "").strip()


def create_google_doc(token: str, name: str, text: str) -> dict:
    boundary = "====save5hours_drive===="
    meta = json.dumps(
        {"name": name, "mimeType": "application/vnd.google-apps.document"}
    )
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        DRIVE_UPLOAD,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_n8n(secret: str, file_info: dict, text: str) -> int:
    payload = json.dumps(
        {
            "fileId": file_info.get("id"),
            "name": file_info.get("name"),
            "mimeType": file_info.get("mimeType")
            or "application/vnd.google-apps.document",
            "webViewLink": file_info.get("webViewLink") or "",
            "text": text,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        N8N_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Secret": secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"n8n HTTP {resp.status}")
            return 0
    except urllib.error.HTTPError as err:
        print(f"n8n HTTP {err.code}")
        return 1


def main() -> int:
    clasprc = load_clasprc()
    if not clasprc:
        print("blocked: clasp is not logged in (no ~/.clasprc.json)")
        return 2
    token = access_token(clasprc)
    if not token:
        print("blocked: clasp token missing or expired")
        return 2
    secret = railway_webhook_secret() or load_dotenv().get("N8N_WEBHOOK_SECRET") or ""
    if not secret:
        print("blocked: N8N_WEBHOOK_SECRET missing")
        return 1
    notes = NOTES.read_text(encoding="utf-8")
    name = "Gemini notes — Drive path verification (n8n)"
    try:
        created = create_google_doc(token, name, notes)
    except urllib.error.HTTPError as err:
        print(f"drive HTTP {err.code}")
        return 1
    file_id = str(created.get("id") or "")
    if not file_id or file_id.startswith("inline-"):
        print("blocked: Drive did not return a file id")
        return 1
    print(f"created Drive file id={file_id}")
    return post_n8n(secret, created, notes)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

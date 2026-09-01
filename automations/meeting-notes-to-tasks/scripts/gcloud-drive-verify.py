#!/usr/bin/env python3
"""Create a real Google Doc with gcloud ADC and POST it to n8n.

Uses `gcloud auth print-access-token` after `gcloud auth login --enable-gdrive-access`.
POSTs {fileId, text} to /webhook/public-drive-doc (no WEBHOOK_SECRET, not the paella
fixture, not /webhook/meeting-notes). Exit 2 if gcloud is not logged in.
Does not print tokens.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "fixtures" / "drive-verify-notes.txt"
PUBLIC_WEBHOOK = "https://n8n-production-192e.up.railway.app/webhook/public-drive-doc"
DRIVE_UPLOAD = (
    "https://www.googleapis.com/upload/drive/v3/files"
    "?uploadType=multipart&fields=id,name,webViewLink,mimeType"
)
TITLE = "Gemini notes — Drive path verification (n8n)"
GCLOUD_CANDIDATES = [
    Path.home() / "google-cloud-sdk-dl" / "google-cloud-sdk" / "bin" / "gcloud",
    Path("/usr/bin/gcloud"),
]


def gcloud_bin() -> str:
    for path in GCLOUD_CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    found = shutil.which("gcloud")
    return found or ""


def access_token(gcloud: str | None = None) -> str:
    binary = gcloud if gcloud is not None else gcloud_bin()
    if not binary:
        return ""
    proc = subprocess.run(
        [binary, "auth", "print-access-token"],
        check=False,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


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


def post_public_webhook(file_info: dict, text: str) -> int:
    file_id = str(file_info.get("id") or "")
    url = file_info.get("webViewLink") or f"https://docs.google.com/document/d/{file_id}/edit"
    payload = json.dumps(
        {
            "fileId": file_id,
            "url": url,
            "name": file_info.get("name") or TITLE,
            "mimeType": file_info.get("mimeType")
            or "application/vnd.google-apps.document",
            "webViewLink": url,
            "text": text,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        PUBLIC_WEBHOOK,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"public-drive-doc HTTP {resp.status}")
            return 0
    except urllib.error.HTTPError as err:
        print(f"public-drive-doc HTTP {err.code}")
        return 1


def run(token: str, notes: str) -> int:
    if not token:
        print("blocked: gcloud is not logged in (no access token)")
        return 2
    try:
        created = create_google_doc(token, TITLE, notes)
    except urllib.error.HTTPError as err:
        print(f"drive HTTP {err.code}")
        return 1
    file_id = str(created.get("id") or "")
    if not file_id or file_id.startswith("inline-"):
        print("blocked: Drive did not return a file id")
        return 1
    print(f"created Drive file id={file_id}")
    return post_public_webhook(created, notes)


def main() -> int:
    notes = NOTES.read_text(encoding="utf-8")
    if "Antoine will publish the Drive webhook runbook" not in notes:
        print("blocked: verification notes fixture missing assignees")
        return 1
    return run(access_token(), notes)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

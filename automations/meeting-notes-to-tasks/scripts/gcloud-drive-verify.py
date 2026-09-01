#!/usr/bin/env python3
"""Create a real Google Doc with gcloud ADC and POST it to n8n.

Uses `gcloud auth print-access-token` (or ADC) after `gcloud auth login
--enable-gdrive-access`. POSTs {fileId, text} to /webhook/public-drive-doc
(no WEBHOOK_SECRET, not the paella fixture, not /webhook/meeting-notes).
Exit 2 if gcloud is not logged in. Does not print tokens or verification codes.

`--watch` polls the Drive-setup workflow for a pasted Google verification code
so HQ empty-polls cannot bury that POST in the global executions list.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
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
N8N_BASE = "https://n8n-production-192e.up.railway.app"
DRIVE_SETUP_WF = "RU7qrw4zZPhZh6Kw"
GCLOUD_CANDIDATES = [
    Path.home() / "google-cloud-sdk-dl" / "google-cloud-sdk" / "bin" / "gcloud",
    Path("/usr/bin/gcloud"),
]
TMUX_SESSION = "gcloud-drive-login"
TMUX_CONF = "/exec-daemon/tmux.portal.conf"


def gcloud_bin() -> str:
    for path in GCLOUD_CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    found = shutil.which("gcloud")
    return found or ""


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


def parse_gcloud_auth_code(src) -> str:
    """Pull a Google verification code from an n8n webhook item. Never log it."""
    root = src if isinstance(src, dict) else {}
    body = root.get("body")
    if isinstance(body, str):
        raw = body.strip()
        parsed: dict = {}
        if raw.startswith("{"):
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = {}
        elif "=" in raw:
            from urllib.parse import parse_qs

            parsed = {k: (v[-1] if v else "") for k, v in parse_qs(raw).items()}
        body = parsed
    if not isinstance(body, dict):
        body = {}
    code = str(body.get("code") or root.get("code") or "").strip()
    if not code or code.startswith("http") or "accounts.google.com" in code.lower():
        return ""
    if any(ch.isspace() for ch in code) or len(code) < 8:
        return ""
    return code


def submit_code_to_tmux(code: str) -> bool:
    if not code:
        return False
    conf = ["-f", TMUX_CONF] if Path(TMUX_CONF).is_file() else []
    proc = subprocess.run(
        ["tmux", *conf, "has-session", "-t", f"={TMUX_SESSION}"],
        check=False,
        capture_output=True,
        timeout=10,
    )
    if proc.returncode != 0:
        print("blocked: gcloud tmux session is not running")
        return False
    subprocess.run(
        [
            "tmux",
            *conf,
            "send-keys",
            "-t",
            f"{TMUX_SESSION}:0.0",
            code,
            "C-m",
        ],
        check=False,
        capture_output=True,
        timeout=10,
    )
    print("submitted gcloud verification code to waiting login")
    return True


def executions_list_url() -> str:
    query = urllib.parse.urlencode(
        {"workflowId": DRIVE_SETUP_WF, "limit": 50}
    )
    return f"{N8N_BASE}/api/v1/executions?{query}"


def n8n_latest_auth_code(api_key: str, seen: set[str] | None = None) -> str:
    """Return a pasted Google verification code. Never log it.

    Reads the Drive-setup workflow only. The meeting-notes HQ poll fires every
    minute and would otherwise push this POST out of a global last-20 list.
    """
    req = urllib.request.Request(
        executions_list_url(),
        headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        listed = json.loads(resp.read().decode("utf-8"))
    for row in listed.get("data") or []:
        if row.get("mode") != "webhook":
            continue
        eid = str(row.get("id") or "")
        if not eid or (seen is not None and eid in seen):
            continue
        detail_req = urllib.request.Request(
            f"{N8N_BASE}/api/v1/executions/{eid}?includeData=true",
            headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(detail_req, timeout=30) as resp:
            detail = json.loads(resp.read().decode("utf-8"))
        run = (detail.get("data") or {}).get("resultData") or {}
        nodes = run.get("runData") or {}
        if "Gcloud auth code" not in nodes:
            continue
        for item_run in nodes["Gcloud auth code"]:
            mains = ((item_run.get("data") or {}).get("main") or [[]])[0]
            for item in mains or []:
                found = parse_gcloud_auth_code(item.get("json") or {})
                if found:
                    if seen is not None:
                        seen.add(eid)
                    return found
    return ""


def access_token(gcloud: str | None = None) -> str:
    binary = gcloud if gcloud is not None else gcloud_bin()
    if not binary:
        return ""
    commands = (
        [binary, "auth", "print-access-token"],
        [binary, "auth", "application-default", "print-access-token"],
    )
    for args in commands:
        proc = subprocess.run(
            args,
            check=False,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            continue
        token = (proc.stdout or "").strip()
        if token and " " not in token and "\n" not in token:
            return token
    return ""


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


def wait_for_token(seconds: int = 30) -> str:
    deadline = time.time() + seconds
    while time.time() < deadline:
        token = access_token()
        if token:
            return token
        time.sleep(2)
    return access_token()


def try_once(notes: str, api_key: str, seen: set[str]) -> int:
    token = access_token()
    if not token and api_key:
        code = n8n_latest_auth_code(api_key, seen)
        if code and submit_code_to_tmux(code):
            token = wait_for_token(30)
    return run(token, notes)


def watch(notes: str, api_key: str, interval: int) -> int:
    seen: set[str] = set()
    while True:
        rc = try_once(notes, api_key, seen)
        if rc == 0:
            return 0
        print("waiting for Google verification code or gcloud ADC")
        time.sleep(max(5, interval))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll Drive-setup for a verification code until a real Doc is posted",
    )
    parser.add_argument("--interval", type=int, default=15)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    notes = NOTES.read_text(encoding="utf-8")
    if "Antoine will publish the Drive webhook runbook" not in notes:
        print("blocked: verification notes fixture missing assignees")
        return 1
    env = load_dotenv()
    api_key = env.get("N8N_API_KEY") or os.environ.get("N8N_API_KEY") or ""
    if args.watch:
        return watch(notes, api_key, args.interval)
    return try_once(notes, api_key, set())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

#!/usr/bin/env python3
"""Create a real Google Doc with gcloud ADC or Drive-only OAuth and POST it to n8n.

Uses a Drive-only Cloud SDK PKCE session (no Cloud Platform / Cloud CLI
scopes) when present, else `gcloud auth print-access-token` after
`gcloud auth login --enable-gdrive-access`. POSTs {fileId, text} to
/webhook/public-drive-doc (no WEBHOOK_SECRET, not the paella fixture, not
/webhook/meeting-notes). Exit 2 if Google is not logged in. Does not print
tokens or verification codes.

`--watch` polls Drive-setup for a pasted Google verification code so HQ
empty-polls cannot bury that POST in the global executions list.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
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
MEETING_NOTES_WF = "9JlE8lA1TQdlxw0S"
AUTH_CODE_NODE = "Gcloud auth code"
GCLOUD_CANDIDATES = [
    Path.home() / "google-cloud-sdk-dl" / "google-cloud-sdk" / "bin" / "gcloud",
    Path("/usr/bin/gcloud"),
]
SDK_CONFIG_CANDIDATES = [
    Path.home()
    / "google-cloud-sdk-dl"
    / "google-cloud-sdk"
    / "lib"
    / "googlecloudsdk"
    / "core"
    / "config.py",
    Path("/usr/lib/google-cloud-sdk/lib/googlecloudsdk/core/config.py"),
]
TMUX_SESSION = "gcloud-drive-login"
TMUX_CONF = "/exec-daemon/tmux.portal.conf"
DRIVE_CONFIRM_PAGE = "3cd0b26fcc4e819bb9ead19d74fb64a6"
GCLOUD_ACCOUNT = "antoine@save5hours.ch"
# Restarting gcloud mints a new code_challenge and invalidates a consent
# screen already open on a phone. Keep the waiting login long enough for that.
# Drive-only PKCE (no Cloud CLI scopes) does not rotate.
PKCE_REFRESH_AFTER = 25 * 60
PUBLISHER = ROOT / "scripts" / "n8n-publish-apps-script-source.py"
DRIVE_OAUTH_SESSION = (
    Path.home() / ".config" / "gcloud" / "drive-verify-oauth.json"
)
ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
OAUTH_REDIRECT = "https://sdk.cloud.google.com/authcode.html"
# Same Drive scope gcloud --enable-gdrive-access uses, without Cloud Platform.
DRIVE_OAUTH_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive",
)
# Google Cloud SDK authcode.html values look like 4/0A…
GCLOUD_CODE_RE = re.compile(r"4/[0-9A-Za-z_\-]{10,}")


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


def cloud_sdk_oauth_client() -> tuple[str, str]:
    """Return the public Cloud SDK installed-app client. Never log the secret."""
    for path in SDK_CONFIG_CANDIDATES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        client = re.search(r"CLOUDSDK_CLIENT_ID = '([^']+)'", text)
        secret = re.search(r"CLOUDSDK_CLIENT_NOTSOSECRET = '([^']+)'", text)
        if client and secret:
            return client.group(1), secret.group(1)
    return "", ""


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def build_drive_auth_url(
    client_id: str, challenge: str, state: str, login_hint: str = GCLOUD_ACCOUNT
) -> str:
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": OAUTH_REDIRECT,
        "scope": " ".join(DRIVE_OAUTH_SCOPES),
        "state": state,
        "prompt": "consent",
        "access_type": "offline",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "login_hint": login_hint,
    }
    return OAUTH_AUTH_URL + "?" + urllib.parse.urlencode(query)


def load_drive_oauth_session() -> dict:
    path = DRIVE_OAUTH_SESSION
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    url = str(data.get("url") or "")
    verifier = str(data.get("verifier") or "")
    if not url.startswith(OAUTH_AUTH_URL) or not verifier:
        return {}
    if "cloud-platform" in url:
        return {}
    return data


def save_drive_oauth_session(data: dict) -> None:
    path = DRIVE_OAUTH_SESSION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, 0o600)


def ensure_drive_oauth_session() -> dict:
    """Stable Drive-only PKCE. Does not rotate; Cloud CLI login is a fallback."""
    existing = load_drive_oauth_session()
    if existing:
        return existing
    client_id, secret = cloud_sdk_oauth_client()
    if not client_id or not secret:
        print("blocked: Cloud SDK OAuth client missing")
        return {}
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    url = build_drive_auth_url(client_id, challenge, state)
    data = {
        "url": url,
        "verifier": verifier,
        "challenge": challenge,
        "state": state,
        "client_id": client_id,
    }
    save_drive_oauth_session(data)
    print("created Drive-only Google authorize session")
    return data


def write_adc(refresh_token: str, client_id: str, client_secret: str) -> None:
    if not refresh_token or not client_id or not client_secret:
        return
    ADC_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "account": GCLOUD_ACCOUNT,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "type": "authorized_user",
        "universe_domain": "googleapis.com",
    }
    ADC_PATH.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(ADC_PATH, 0o600)


def exchange_drive_code(code: str, session: dict | None = None) -> str:
    """Exchange a pasted Google code for a Drive access token. Never log it."""
    compact = "".join(str(code or "").split())
    if not compact:
        return ""
    session = session if session is not None else load_drive_oauth_session()
    verifier = str((session or {}).get("verifier") or "")
    client_id = str((session or {}).get("client_id") or "")
    sdk_id, sdk_secret = cloud_sdk_oauth_client()
    client_id = client_id or sdk_id
    if not verifier or not client_id or not sdk_secret:
        return ""
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": sdk_secret,
            "code": compact,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": OAUTH_REDIRECT,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        print("blocked: Google Drive token exchange failed")
        return ""
    except (TimeoutError, urllib.error.URLError, OSError, json.JSONDecodeError):
        print("blocked: Google Drive token exchange failed")
        return ""
    token = str(parsed.get("access_token") or "").strip()
    refresh = str(parsed.get("refresh_token") or "").strip()
    if not token or " " in token or "\n" in token:
        print("blocked: Google Drive token exchange failed")
        return ""
    if refresh:
        write_adc(refresh, client_id, sdk_secret)
    print("exchanged Google Drive token")
    return token


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
    query = root.get("query") if isinstance(root.get("query"), dict) else {}
    raw_code = body.get("code") or query.get("code") or root.get("code") or ""
    if isinstance(raw_code, list):
        raw_code = raw_code[-1] if raw_code else ""
    # Google's authcode page wraps the value; pasted codes often include newlines.
    code = "".join(str(raw_code).split())
    if not code or code.startswith("http") or "accounts.google.com" in code.lower():
        code = ""
    elif len(code) < 8:
        code = ""
    if code:
        return code
    blobs: list[str] = []
    for layer in (body, query, root):
        if isinstance(layer, dict):
            for value in layer.values():
                if isinstance(value, str):
                    blobs.append(value)
        elif isinstance(layer, str):
            blobs.append(layer)
    for blob in blobs:
        if blob == raw_code:
            continue
        found = extract_gcloud_code_from_text(blob)
        if found:
            return found
    return ""


def extract_gcloud_code_from_text(text: str) -> str:
    """Find a Google verification code in free-form text. Never log it."""
    raw = str(text or "")
    match = GCLOUD_CODE_RE.search(raw)
    if not match:
        match = GCLOUD_CODE_RE.search("".join(raw.split()))
    if not match:
        return ""
    return parse_gcloud_auth_code({"code": match.group(0)})


def iter_execution_jsons(detail: dict, node_name: str = ""):
    run = (detail.get("data") or {}).get("resultData") or {}
    nodes = run.get("runData") or {}
    if node_name:
        if node_name not in nodes:
            return
        selected = {node_name: nodes[node_name]}
    else:
        selected = nodes
    for runs in selected.values():
        for item_run in runs or []:
            mains = ((item_run.get("data") or {}).get("main") or [[]])[0]
            for item in mains or []:
                yield item.get("json") or {}


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


def tmux_args(*extra: str) -> list[str]:
    conf = ["-f", TMUX_CONF] if Path(TMUX_CONF).is_file() else []
    return ["tmux", *conf, *extra]


def unwrap_gcloud_auth_urls(text: str) -> str:
    """Join tmux-wrapped Google authorize URLs so PKCE is not truncated."""
    lines = (text or "").splitlines()
    out: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            out.append(buf)
            buf = ""

    for line in lines:
        stripped = line.strip()
        if buf:
            if (
                not stripped
                or stripped.startswith("Once finished")
                or stripped.startswith("Go to the following")
                or stripped.startswith("https://")
            ):
                flush()
            else:
                buf += stripped
                if "code_challenge_method=" in buf:
                    flush()
                continue
        idx = stripped.find("https://accounts.google.com/o/oauth2/auth")
        if idx >= 0:
            buf = stripped[idx:]
            if "code_challenge_method=" in buf:
                flush()
            continue
        out.append(line)
    flush()
    return "\n".join(out)


def pkce_challenges(text: str) -> list[str]:
    return re.findall(r"code_challenge=([^&\s]+)", unwrap_gcloud_auth_urls(text))


def pane_has_new_pkce(text: str, previous: set[str]) -> bool:
    """True when tmux shows a waiting login whose PKCE is not in previous."""
    found = pkce_challenges(text)
    return bool(found) and "Once finished" in (text or "") and any(
        item not in previous for item in found
    )


def capture_gcloud_pane() -> str:
    pane = subprocess.run(
        tmux_args(
            "capture-pane",
            "-t",
            f"{TMUX_SESSION}:0.0",
            "-J",
            "-p",
            "-S",
            "-80",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return pane.stdout or ""


def gcloud_login_elapsed_seconds() -> float | None:
    proc = subprocess.run(
        ["pgrep", "-f", "gcloud.py auth login"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    pids = [p for p in (proc.stdout or "").split() if p.isdigit()]
    if not pids:
        return None
    ps = subprocess.run(
        ["ps", "-p", pids[0], "-o", "etimes="],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    try:
        return float((ps.stdout or "").strip().split()[0])
    except (ValueError, IndexError):
        return None


def restart_gcloud_login() -> bool:
    binary = gcloud_bin()
    if not binary:
        print("blocked: gcloud binary missing")
        return False
    has = subprocess.run(
        tmux_args("has-session", "-t", f"={TMUX_SESSION}"),
        check=False,
        capture_output=True,
        timeout=10,
    )
    if has.returncode != 0:
        print("blocked: gcloud tmux session is not running")
        return False
    previous = set(pkce_challenges(capture_gcloud_pane()))
    subprocess.run(
        tmux_args("send-keys", "-t", f"{TMUX_SESSION}:0.0", "C-c"),
        check=False,
        capture_output=True,
        timeout=10,
    )
    time.sleep(1)
    cmd = (
        f"{binary} auth login --no-launch-browser --enable-gdrive-access "
        f"--update-adc --account={GCLOUD_ACCOUNT}"
    )
    subprocess.run(
        tmux_args("send-keys", "-t", f"{TMUX_SESSION}:0.0", cmd, "C-m"),
        check=False,
        capture_output=True,
        timeout=10,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if pane_has_new_pkce(capture_gcloud_pane(), previous):
            print("refreshed gcloud login PKCE")
            return True
        time.sleep(1)
    print("blocked: gcloud login did not print an authorize URL")
    return False


def publish_drive_setup() -> bool:
    if not PUBLISHER.is_file():
        print("blocked: Drive setup publisher missing")
        return False
    proc = subprocess.run(
        [sys.executable, str(PUBLISHER)],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        print("blocked: Drive setup republish failed")
        return False
    print("republished Drive setup for PKCE")
    return True


def maybe_refresh_gcloud_pkce(after: int = PKCE_REFRESH_AFTER) -> bool:
    """Restart waiting gcloud login and republish Authorize when PKCE is stale.

    Drive-only PKCE does not rotate — restarting gcloud would mint a different
    challenge than the Authorize link already on Drive setup.
    """
    if load_drive_oauth_session():
        return False
    elapsed = gcloud_login_elapsed_seconds()
    if elapsed is not None and elapsed < after:
        return False
    if not restart_gcloud_login():
        return False
    return publish_drive_setup()


def executions_list_url(workflow_id: str = DRIVE_SETUP_WF) -> str:
    query = urllib.parse.urlencode(
        {
            "workflowId": workflow_id,
            "limit": 50,
            "includeData": "true",
        }
    )
    return f"{N8N_BASE}/api/v1/executions?{query}"


def n8n_get_json(req: urllib.request.Request, timeout: int = 45) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def n8n_latest_auth_code(api_key: str, seen: set[str] | None = None) -> str:
    """Return a pasted Google verification code. Never log it.

    Reads Drive-setup `Gcloud auth code` POSTs first. GET authorize-link
    executions are ignored. Then scans meeting-notes webhooks (a 4/ code
    pasted in the Doc URL field without JS hits public-drive-doc). Timeouts
    return empty so --watch can keep polling.
    """
    req = urllib.request.Request(
        executions_list_url(),
        headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
    )
    try:
        listed = n8n_get_json(req)
    except (TimeoutError, urllib.error.URLError, OSError):
        print("n8n executions list timed out")
        return ""
    for row in listed.get("data") or []:
        if row.get("mode") != "webhook":
            continue
        eid = str(row.get("id") or "")
        if not eid or (seen is not None and eid in seen):
            continue
        detail = row
        run_data = ((detail.get("data") or {}).get("resultData") or {}).get("runData") or {}
        if not run_data:
            detail_req = urllib.request.Request(
                f"{N8N_BASE}/api/v1/executions/{eid}?includeData=true",
                headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
            )
            try:
                detail = n8n_get_json(detail_req)
            except (TimeoutError, urllib.error.URLError, OSError):
                print(f"n8n execution {eid} timed out")
                continue
            run_data = ((detail.get("data") or {}).get("resultData") or {}).get("runData") or {}
        if seen is not None:
            seen.add(eid)
        if AUTH_CODE_NODE not in run_data:
            continue
        for payload in iter_execution_jsons(detail, AUTH_CODE_NODE):
            found = parse_gcloud_auth_code(payload)
            if found:
                return found
    return n8n_latest_auth_code_from_workflow(api_key, MEETING_NOTES_WF, seen)


def n8n_latest_auth_code_from_workflow(
    api_key: str, workflow_id: str, seen: set[str] | None = None
) -> str:
    req = urllib.request.Request(
        executions_list_url(workflow_id),
        headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
    )
    try:
        listed = n8n_get_json(req)
    except (TimeoutError, urllib.error.URLError, OSError):
        print("n8n executions list timed out")
        return ""
    for row in listed.get("data") or []:
        if row.get("mode") != "webhook":
            continue
        eid = str(row.get("id") or "")
        if not eid or (seen is not None and eid in seen):
            continue
        detail = row
        run_data = ((detail.get("data") or {}).get("resultData") or {}).get("runData") or {}
        if not run_data:
            detail_req = urllib.request.Request(
                f"{N8N_BASE}/api/v1/executions/{eid}?includeData=true",
                headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
            )
            try:
                detail = n8n_get_json(detail_req)
            except (TimeoutError, urllib.error.URLError, OSError):
                print(f"n8n execution {eid} timed out")
                continue
            run_data = ((detail.get("data") or {}).get("resultData") or {}).get("runData") or {}
        if seen is not None:
            seen.add(eid)
        node = AUTH_CODE_NODE if AUTH_CODE_NODE in run_data else ""
        for payload in iter_execution_jsons(detail, node):
            found = parse_gcloud_auth_code(payload)
            if found:
                return found
    return ""


def hq_confirmation_auth_code(token: str) -> str:
    """Read a pasted Google verification code from the HQ Drive task. Never log it."""
    if not token:
        return ""
    req = urllib.request.Request(
        f"https://api.notion.com/v1/comments?block_id={DRIVE_CONFIRM_PAGE}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        },
        method="GET",
    )
    try:
        comments = n8n_get_json(req, timeout=30)
    except (TimeoutError, urllib.error.URLError, OSError, urllib.error.HTTPError):
        return ""
    for row in comments.get("results") or []:
        rich = row.get("rich_text") or []
        text = "".join(span.get("plain_text") or "" for span in rich)
        found = extract_gcloud_code_from_text(text)
        if found:
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


def try_once(notes: str, api_key: str, seen: set[str], notion_token: str = "") -> int:
    token = access_token()
    if not token:
        code = ""
        if api_key:
            code = n8n_latest_auth_code(api_key, seen)
        if not code:
            code = hq_confirmation_auth_code(notion_token)
        if code:
            token = exchange_drive_code(code)
        if not token and code and submit_code_to_tmux(code):
            token = wait_for_token(30)
    return run(token, notes)


def watch(notes: str, api_key: str, interval: int, notion_token: str = "") -> int:
    session = ensure_drive_oauth_session()
    if session.get("url"):
        publish_drive_setup()
    seen: set[str] = set()
    while True:
        try:
            rc = try_once(notes, api_key, seen, notion_token)
        except (TimeoutError, urllib.error.URLError, OSError) as err:
            print(f"watch iteration failed: {type(err).__name__}")
            rc = 2
        if rc == 0:
            return 0
        maybe_refresh_gcloud_pkce()
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
    notion_token = env.get("NOTION_API_KEY") or os.environ.get("NOTION_API_KEY") or ""
    if args.watch:
        return watch(notes, api_key, args.interval, notion_token)
    return try_once(notes, api_key, set(), notion_token)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

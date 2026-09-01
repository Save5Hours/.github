#!/usr/bin/env python3
"""Publish GET webhooks for the Drive Apps Script (no secrets).

Live URLs:
  https://n8n-production-192e.up.railway.app/webhook/drive-setup
  https://n8n-production-192e.up.railway.app/webhook/apps-script-source

Does not touch the Meeting notes → HQ Tasks workflow.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apps-script-drive-webhook.js"
VERIFY_NOTES = ROOT / "fixtures" / "drive-verify-notes.txt"
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


def extract_gcloud_auth_url(text: str) -> str:
    """Return the newest Google authorize URL from tmux output (PKCE must match)."""
    matches = re.findall(
        r"https://accounts\.google\.com/o/oauth2/auth\S+",
        unwrap_gcloud_auth_urls(text),
    )
    return matches[-1] if matches else ""


def read_gcloud_auth_url() -> str:
    env_url = (os.environ.get("GCLOUD_AUTH_URL") or "").strip()
    if env_url.startswith("https://accounts.google.com/o/oauth2/auth"):
        return env_url
    conf = Path("/exec-daemon/tmux.portal.conf")
    cmd = ["tmux"]
    if conf.is_file():
        cmd += ["-f", str(conf)]
    cmd += ["capture-pane", "-t", "gcloud-drive-login:0.0", "-J", "-p", "-S", "-80"]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
    return extract_gcloud_auth_url(proc.stdout or "")


def setup_html(source: str, gcloud_auth_url: str = "") -> str:
    escaped = html.escape(source)
    sample_notes = html.escape(VERIFY_NOTES.read_text(encoding="utf-8").strip())
    safe = (
        html.escape(gcloud_auth_url, quote=True)
        if gcloud_auth_url.startswith("https://accounts.google.com/o/oauth2/auth")
        else "#"
    )
    auth_link = (
        f'<p><a class="bookmark" id="gcloudauth" href="{safe}" target="_blank" rel="noopener">'
        "Authorize Google Drive</a> (Google Cloud SDK: Drive plus Cloud CLI). "
        "If this tab was already open, the link refreshes by itself. "
        "Then paste the verification code below. Prefer Option 1 if you can paste a Doc URL.</p>"
    )
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Connect Gemini Drive notes</title>
  <style>
    body { font: 16px/1.45 system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; color: #111; }
    ol { padding-left: 1.3rem; }
    a { color: #0b57d0; }
    button { font: inherit; padding: .4rem .8rem; cursor: pointer; }
    textarea.src { width: 100%; min-height: 22rem; font: 12px/1.4 ui-monospace, monospace; }
    textarea.notes { width: 100%; min-height: 10rem; font: 13px/1.4 ui-monospace, monospace; margin-top: .5rem; }
    .ok { color: #0b7; display: none; margin-left: .5rem; }
    .warn { color: #a40; }
    .bookmark { display: inline-block; padding: .35rem .7rem; border: 1px dashed #0b57d0; border-radius: 6px; text-decoration: none; font-weight: 600; }
  </style>
</head>
<body>
  <h1>Connect Gemini Drive notes</h1>
  <p>n8n already writes HQ Tasks from OpenRouter. You do <strong>not</strong> need an n8n login. Chrome often blocks <code>javascript:</code> bookmarks, so <strong>paste URL + notes is the reliable path</strong>. If Apps Script logs HTTP 404, wait a minute and Run <strong>verifyDrivePath</strong> again (the script now retries while n8n finishes booting).</p>
  <h2>Option 1 — paste a Google Doc URL (private Docs work)</h2>
  <p><strong>Fastest:</strong> while signed into Google, <a class="bookmark" href="https://docs.new" target="_blank" rel="noopener">open a new Google Doc</a>, copy the URL from the address bar, paste it below, and click <strong>Send to HQ Tasks</strong>. Sample verification notes are already filled, so the Doc can stay private and empty. Replace the textarea with real Gemini notes when you have them. After send you should see <strong>Received</strong> — HQ Tasks then get that Drive file ID (not <code>inline-*</code>).</p>
  <form id="docform" method="POST" action="/webhook/public-drive-doc" accept-charset="UTF-8">
    <p>
      <input id="docurl" name="url" type="text" inputmode="url" autocomplete="url" required placeholder="https://docs.google.com/document/d/…/edit" style="font:inherit;width:min(100%,28rem);padding:.3rem .5rem"/>
      <input id="docfile" type="file" accept=".txt,text/plain"/>
      <input type="hidden" name="name" value="Gemini notes — Drive path verification (n8n)"/>
      <input type="hidden" name="fileId" id="docfileid" value=""/>
      <button type="button" id="pasteclip">Paste clipboard</button>
      <button type="submit" id="senddoc">Send to HQ Tasks</button>
      <span class="warn" id="docerr"></span>
    </p>
    <textarea class="notes" id="doctext" name="text" placeholder="Paste the Doc text here if it is not shared as Anyone with the link">""" + sample_notes + """</textarea>
  </form>
  <p>A Gemini Doc URL also works. If you clear the text, the Doc must be <strong>Anyone with the link can view</strong>.</p>
  <h2>Option 1b — authorize this agent (it creates the Doc)</h2>
  <p>Use this if you do not want to paste a Doc URL. Prefer Option 1 when you already have Gemini notes.</p>
  """ + auth_link + """
  <form id="gcloudform" method="POST" action="/webhook/gcloud-auth-code" accept-charset="UTF-8">
    <p>
      <input id="gcloudcode" name="code" type="text" autocomplete="off" spellcheck="false" placeholder="Google verification code" style="font:inherit;width:min(100%,22rem);padding:.3rem .5rem"/>
      <button type="submit" id="sendgcloud">Send code to agent</button>
    </p>
  </form>
  <h2>Option 2 — Colab (creates a real Google Doc, one Run all)</h2>
  <p>Signed in as the Meet organizer: <a class="bookmark" href="https://colab.research.google.com/github/Save5Hours/.github/blob/cursor/n8n-meeting-notes-railway-3e35/automations/meeting-notes-to-tasks/scripts/colab_drive_verify.ipynb" target="_blank" rel="noopener">Open Colab — Run all</a></p>
  <p>Runtime → <strong>Run all</strong> → Google sign-in. It creates a Google Doc and POSTs <code>fileId</code> + notes to <code>/webhook/public-drive-doc</code> (no n8n login, no <code>WEBHOOK_SECRET</code>). HQ Tasks should then show a Drive file ID that is not <code>inline-*</code>.</p>
  <h2>Option 3 — bookmarklet or console (same export, private Docs)</h2>
  <p>Drag this link to your bookmarks bar, then open the Gemini Doc on <strong>docs.google.com</strong> and click it. If Chrome strips <code>javascript:</code> bookmarks: open the Doc → F12 → Console → <strong>Copy console snippet</strong> → paste → Enter.</p>
  <p>
    <a class="bookmark" id="bookmarklet" href="#">Send this Doc to HQ Tasks</a>
    <button type="button" id="copybm">Copy bookmarklet</button>
    <button type="button" id="copyconsole">Copy console snippet</button>
    <span class="ok" id="bmok">copied</span>
    <span class="ok" id="conok">copied</span>
  </p>
  <h2>Option 4 — Apps Script (Meet Recordings tree + 1-minute trigger)</h2>
  <p>Sign in to Google as the Meet organizer (<code>@save5hours.ch</code> or the known organizer Gmail).</p>
  <ol>
    <li>Open <a href="https://script.google.com" target="_blank" rel="noopener">script.google.com</a> → <strong>New project</strong>.</li>
    <li>Click <button type="button" id="copy">Copy Apps Script</button><span class="ok" id="ok">copied</span> and paste into the editor.</li>
    <li>Run <strong>verifyDrivePath</strong>. Authorize Drive, Docs, and email if Google asks.</li>
    <li>Paste <code>FOLDER_URL</code> / <code>FILE_ID</code> from the execution log into <a href="https://app.notion.com/p/3cd0b26fcc4e819bb9ead19d74fb64a6" target="_blank" rel="noopener">Confirm the Drive folder</a>.</li>
  </ol>
  <p class="warn">Do not re-POST the paella fixture. The script POSTs <code>fileId</code>+notes to <code>/webhook/public-drive-doc</code> first (no n8n userinfo). It only uses <code>/webhook/meeting-notes-drive</code> if that fails. You do not need <code>WEBHOOK_SECRET</code>.</p>
  <textarea class="src" id="src" readonly>""" + escaped + """</textarea>
  <p><a href="/webhook/apps-script-source">plain-text source</a></p>
  <script>
    const bookmarklet = document.getElementById('bookmarklet');
    const endpoint = location.origin + '/webhook/public-drive-doc';
    const gcloudCodeRe = /^4\\/[0-9A-Za-z_\\-]{10,}$/;
    const asGcloudCode = (value) => {
      const compact = String(value || '').replace(/\\s+/g, '');
      return gcloudCodeRe.test(compact) ? compact : '';
    };
    const sendGcloudCode = (code) => {
      document.getElementById('gcloudcode').value = code;
      document.getElementById('gcloudform').submit();
    };
    const src = [
      '(async()=>{try{',
      'const parts=location.pathname.split("/");',
      'let id="";',
      'for(let i=0;i<parts.length;i++){if(parts[i]==="d"&&parts[i+1]&&parts[i+1].length>=10)id=parts[i+1];}',
      'if(!id){try{id=new URLSearchParams(location.search).get("id")||"";}catch(e){id="";}}',
      'if(!id){alert("Open a Google Doc tab first (docs.google.com).");return;}',
      'const res=await fetch("https://docs.google.com/document/d/"+id+"/export?format=txt",{credentials:"include"});',
      'const text=await res.text();',
      'const compact=text.replace(/\\\\s+/g," ").trim();',
      'if(!res.ok||compact.length<80||(/<html/i.test(text)&&/sign in/i.test(text))){',
      'alert("Could not read this Doc. Stay on the docs.google.com tab while signed in.");return;}',
      'const f=document.createElement("form");f.method="POST";f.action=' + JSON.stringify(endpoint) + ';',
      'const add=(n,v)=>{const t=document.createElement("textarea");t.name=n;t.value=v;f.appendChild(t);};',
      'add("fileId",id);add("url",location.href);add("name",document.title||"Gemini notes");add("text",text);',
      'document.documentElement.appendChild(f);f.submit();',
      '}catch(err){alert(String(err));}})()'
    ].join("");
    const href = 'javascript:' + encodeURIComponent(src);
    bookmarklet.href = href;
    bookmarklet.onclick = (event) => {
      if (!location.hostname.includes('docs.google')) {
        event.preventDefault();
        alert('Drag this link to your bookmarks bar, then click it on a Google Doc tab.');
      }
    };
    document.getElementById('copybm').onclick = async () => {
      await navigator.clipboard.writeText(href);
      document.getElementById('bmok').style.display = 'inline';
    };
    document.getElementById('copyconsole').onclick = async () => {
      await navigator.clipboard.writeText(src);
      document.getElementById('conok').style.display = 'inline';
    };
    document.getElementById('copy').onclick = async () => {
      await navigator.clipboard.writeText(document.getElementById('src').value);
      document.getElementById('ok').style.display = 'inline';
    };
    document.getElementById('pasteclip').onclick = async () => {
      const err = document.getElementById('docerr');
      err.textContent = '';
      let clip = '';
      try { clip = await navigator.clipboard.readText(); } catch (e) {
        err.textContent = 'allow clipboard, or paste into the fields';
        return;
      }
      const pastedCode = asGcloudCode(clip);
      if (pastedCode) {
        err.textContent = 'that looks like a Google verification code — sending to the agent';
        sendGcloudCode(pastedCode);
        return;
      }
      const match = clip.match(/https?:\\/\\/(?:docs|drive)\\.google\\.com\\S+/i);
      if (match) {
        document.getElementById('docurl').value = match[0];
        const rest = clip.replace(match[0], '').trim();
        if (rest) document.getElementById('doctext').value = rest;
      } else if (clip.trim()) {
        document.getElementById('doctext').value = clip;
      }
    };
    document.getElementById('docfile').onchange = async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      document.getElementById('doctext').value = await file.text();
    };
    const newDocLink = document.querySelector('a[href="https://docs.new"]');
    if (newDocLink) {
      newDocLink.addEventListener('click', () => {
        const urlEl = document.getElementById('docurl');
        urlEl.focus();
        const err = document.getElementById('docerr');
        err.textContent = 'after the new tab shows docs.google.com/document/d/… paste that URL here';
      });
    }
    document.getElementById('gcloudform').onsubmit = () => {
      const el = document.getElementById('gcloudcode');
      el.value = el.value.replace(/\\s+/g, '');
    };
    const refreshAuth = async () => {
      const el = document.getElementById('gcloudauth');
      if (!el) return;
      try {
        const res = await fetch('/webhook/gcloud-auth-url', { cache: 'no-store' });
        const href = (await res.text()).trim();
        if (href.indexOf('https://accounts.google.com/o/oauth2/auth') === 0) {
          el.href = href;
        }
      } catch (e) {}
    };
    refreshAuth();
    setInterval(refreshAuth, 30000);
    document.getElementById('docform').onsubmit = (event) => {
      const err = document.getElementById('docerr');
      err.textContent = '';
      const urlEl = document.getElementById('docurl');
      let url = urlEl.value.trim();
      if (url && !/^https?:\\/\\//i.test(url) && /(docs|drive)\\.google\\.com/i.test(url)) {
        url = 'https://' + url.replace(/^\\/+/, '');
        urlEl.value = url;
      }
      const text = document.getElementById('doctext').value.trim();
      const authCode = asGcloudCode(url) || asGcloudCode(text);
      if (authCode) {
        event.preventDefault();
        sendGcloudCode(authCode);
        return;
      }
      const idMatch = url.match(/\\/d\\/([a-zA-Z0-9_-]{10,})/) || url.match(/[?&](?:id|fileId)=([a-zA-Z0-9_-]{10,})/i);
      document.getElementById('docfileid').value = idMatch ? idMatch[1] : '';
      if (!url) { event.preventDefault(); err.textContent = 'paste a Google Doc URL'; return; }
      if (/docs\\.new/i.test(url) || !idMatch) {
        event.preventDefault();
        err.textContent = 'wait until the address bar shows docs.google.com/document/d/… then paste that URL (not docs.new)';
        return;
      }
      if (!/(docs|drive)\\.google\\.com/i.test(url)) {
        event.preventDefault();
        err.textContent = 'use a docs.google.com or drive.google.com link';
        return;
      }
      if (text && text.replace(/\\s+/g, ' ').length < 80) {
        event.preventDefault();
        err.textContent = 'notes text is too short (need ~80+ characters), or leave it empty for a public Doc';
      }
    };
  </script>
</body>
</html>
"""


CODE_RECEIVED_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><title>Code received</title></head>
<body style="font:16px/1.45 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem">
<p>Code received. The agent will create a Google Doc and send it to HQ Tasks (Drive file ID will not be <code>inline-*</code>).</p>
<p><a href="/webhook/drive-setup">Back to Drive setup</a></p>
</body></html>
"""


def webhook_node(
    node_id: str,
    name: str,
    path: str,
    body: str,
    content_type: str,
    x: int,
    method: str = "GET",
) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [x, 0],
        "webhookId": path,
        "parameters": {
            "httpMethod": method,
            "path": path,
            "responseMode": "onReceived",
            "options": {
                "responseData": body,
                "responseHeaders": {
                    "entries": [
                        {"name": "Content-Type", "value": content_type},
                        {
                            "name": "Cache-Control",
                            "value": "no-store, no-cache, must-revalidate",
                        },
                    ]
                },
            },
        },
    }


def workflow_payload(source: str, gcloud_auth_url: str = "") -> dict:
    return {
        "name": WF_NAME,
        "nodes": [
            webhook_node(
                "apps-script-source",
                "Apps Script source",
                "apps-script-source",
                source,
                "text/plain; charset=utf-8",
                0,
            ),
            webhook_node(
                "drive-setup",
                "Drive setup page",
                "drive-setup",
                setup_html(source, gcloud_auth_url),
                "text/html; charset=utf-8",
                280,
            ),
            webhook_node(
                "gcloud-auth-code",
                "Gcloud auth code",
                "gcloud-auth-code",
                CODE_RECEIVED_HTML,
                "text/html; charset=utf-8",
                560,
                method="POST",
            ),
            webhook_node(
                "gcloud-auth-url",
                "Gcloud auth URL",
                "gcloud-auth-url",
                (
                    gcloud_auth_url
                    if gcloud_auth_url.startswith(
                        "https://accounts.google.com/o/oauth2/auth"
                    )
                    else ""
                ),
                "text/plain; charset=utf-8",
                840,
            ),
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
    if "meeting-notes-drive" not in source or "ScriptApp.getOAuthToken" not in source:
        print("blocked: Apps Script source missing Drive Google-token path")
        return 1
    if "public-drive-doc" not in source or "PUBLIC_WEBHOOK" not in source:
        print("blocked: Apps Script source must POST public-drive-doc first")
        return 1
    if "Utilities.sleep" not in source or "not registered" not in source:
        print("blocked: Apps Script source missing webhook retry")
        return 1
    payload = workflow_payload(source, read_gcloud_auth_url())
    code, listed = request(api_key, "GET", "/api/v1/workflows")
    workflows = listed.get("data") if isinstance(listed, dict) else []
    existing = next((w for w in (workflows or []) if w.get("name") == WF_NAME), None)
    if existing:
        wf_id = existing["id"]
        if existing.get("active"):
            code, body = request(api_key, "POST", f"/api/v1/workflows/{wf_id}/deactivate")
            print(f"deactivate {wf_id} status={code}")
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
        print(f"GET source HTTP {resp.status} bytes={len(text)}")
        if "function verifyDrivePath(" not in text:
            print("blocked: webhook body is not the Apps Script")
            return 1
    req = urllib.request.Request(f"{N8N_URL}/webhook/drive-setup", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")
        print(f"GET setup HTTP {resp.status} bytes={len(page)}")
        if "verifyDrivePath" not in page or "<!doctype html>" not in page.lower():
            print("blocked: drive-setup page missing HTML")
            return 1
        if 'id="copy"' not in page or "script.google.com" not in page:
            print("blocked: drive-setup page missing Copy / Apps Script steps")
            return 1
        if 'id="senddoc"' not in page or "public-drive-doc" not in page:
            print("blocked: drive-setup page missing public Doc form")
            return 1
        if 'id="docform"' not in page or 'method="POST"' not in page:
            print("blocked: drive-setup page must POST the Doc form")
            return 1
        if 'id="docurl"' in page and 'name="url" type="url"' in page:
            print("blocked: Doc URL field must not use type=url (browser blocks pastes without https)")
            return 1
        if 'id="bookmarklet"' not in page or "Send this Doc to HQ Tasks" not in page:
            print("blocked: drive-setup page missing bookmarklet")
            return 1
        if "URLSearchParams" not in page or 'get("id")' not in page:
            print("blocked: bookmarklet must read docs.google.com/open?id=")
            return 1
        if 'id="doctext"' not in page:
            print("blocked: drive-setup page missing private-Doc text paste")
            return 1
        if 'name="fileId"' not in page or 'id="docfileid"' not in page:
            print("blocked: drive-setup form must POST fileId extracted from the Doc URL")
            return 1
        if 'id="pasteclip"' not in page or 'id="copyconsole"' not in page:
            print("blocked: drive-setup page missing clipboard / console helpers")
            return 1
        if "colab.research.google.com" not in page or "colab_drive_verify" not in page:
            print("blocked: drive-setup page missing Colab Run-all path")
            return 1
        if "Open Colab" not in page or "public-drive-doc" not in page:
            print("blocked: drive-setup Colab path must POST public-drive-doc")
            return 1
        if "docs.new" not in page:
            print("blocked: drive-setup page missing docs.new shortcut")
            return 1
        if "not docs.new" not in page:
            print("blocked: drive-setup form must reject docs.new without a file id")
            return 1
        if 'id="gcloudcode"' not in page or "gcloud-auth-code" not in page:
            print("blocked: drive-setup page missing gcloud verification-code form")
            return 1
        if 'id="gcloudauth"' not in page or "gcloud-auth-url" not in page:
            print("blocked: drive-setup page missing live Google authorize link")
            return 1
        if "cache: 'no-store'" not in page or "setInterval(refreshAuth" not in page:
            print("blocked: drive-setup page must refresh the authorize link")
            return 1
        if "asGcloudCode" not in page or "sendGcloudCode" not in page:
            print("blocked: drive-setup page must accept a verification code in the Doc URL field")
            return 1
        auth_url = read_gcloud_auth_url()
        if auth_url:
            req = urllib.request.Request(f"{N8N_URL}/webhook/gcloud-auth-url", method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                live_url = html.unescape(resp.read().decode("utf-8", errors="replace").strip())
            live_chal = re.search(r"code_challenge=([^&\s]+)", live_url)
            want_chal = re.search(r"code_challenge=([^&\s]+)", auth_url)
            if not live_chal or not want_chal or live_chal.group(1) != want_chal.group(1):
                print("blocked: gcloud-auth-url PKCE does not match tmux")
                return 1
        if "Drive path verification" not in page:
            print("blocked: drive-setup form must prefill verification notes")
            return 1
        if 'id="secret"' in page or "filledSource" in page:
            print("blocked: drive-setup page still asks for the n8n webhook secret")
            return 1
        if 'WEBHOOK_SECRET_PASTE = "' in page and 'WEBHOOK_SECRET_PASTE = "";' not in page:
            print("blocked: setup page leaked a filled webhook secret")
            return 1
    print("apps-script-source and drive-setup webhooks are live")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

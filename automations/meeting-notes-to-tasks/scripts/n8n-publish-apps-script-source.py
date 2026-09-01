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


def setup_html(source: str) -> str:
    escaped = html.escape(source)
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
  <h2>Option 1 — paste URL + notes (private Docs work)</h2>
  <p>In the Gemini Doc: copy the URL, then <strong>Ctrl+A / Ctrl+C</strong> (or File → Download → Plain text). Paste both here, or use <strong>Paste clipboard</strong>. n8n keeps that Drive file ID. Sharing can stay private. After send you should see <strong>Received</strong> and the Drive file ID — not a blank page.</p>
  <form id="docform" method="POST" action="/webhook/public-drive-doc" accept-charset="UTF-8">
    <p>
      <input id="docurl" name="url" type="text" inputmode="url" autocomplete="url" required placeholder="https://docs.google.com/document/d/…/edit" style="font:inherit;width:min(100%,28rem);padding:.3rem .5rem"/>
      <input id="docfile" type="file" accept=".txt,text/plain"/>
      <input type="hidden" name="name" value="Gemini notes"/>
      <button type="button" id="pasteclip">Paste clipboard</button>
      <button type="submit" id="senddoc">Send to HQ Tasks</button>
      <span class="warn" id="docerr"></span>
    </p>
    <textarea class="notes" id="doctext" name="text" placeholder="Paste the Doc text here if it is not shared as Anyone with the link"></textarea>
  </form>
  <p>If you only paste the URL and leave the text empty, the Doc must be <strong>Anyone with the link can view</strong>.</p>
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
      if (!url) { event.preventDefault(); err.textContent = 'paste a Google Doc URL'; return; }
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


def webhook_node(node_id: str, name: str, path: str, body: str, content_type: str, x: int) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [x, 0],
        "webhookId": path,
        "parameters": {
            "httpMethod": "GET",
            "path": path,
            "responseMode": "onReceived",
            "options": {
                "responseData": body,
                "responseHeaders": {
                    "entries": [{"name": "Content-Type", "value": content_type}]
                },
            },
        },
    }


def workflow_payload(source: str) -> dict:
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
                setup_html(source),
                "text/html; charset=utf-8",
                280,
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
    payload = workflow_payload(source)
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
        if 'id="pasteclip"' not in page or 'id="copyconsole"' not in page:
            print("blocked: drive-setup page missing clipboard / console helpers")
            return 1
        if "colab.research.google.com" not in page or "colab_drive_verify" not in page:
            print("blocked: drive-setup page missing Colab Run-all path")
            return 1
        if "Open Colab" not in page or "public-drive-doc" not in page:
            print("blocked: drive-setup Colab path must POST public-drive-doc")
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

#!/usr/bin/env python3
"""Overwrite the live Meeting notes → HQ Tasks canvas via Railway SSH.

Keeps live credential ids and the existing workflow row. Drive triggers stay
disabled until a folder ID and Google OAuth client exist. Restarts n8n so the
editor picks up the sqlite patch.

Requires `railway login` or RAILWAY_TOKEN. Never prints secret values.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_SRC = ROOT / "n8n" / "meeting-notes-to-tasks.json"
PROJECT = "48651271-91e5-4a40-8783-6971a438c2a3"
SERVICE = "n8n"
ENV = "production"
WF_NAME = "Meeting notes → HQ Tasks"
N8N_URL = "https://n8n-production-192e.up.railway.app"
PLACEHOLDER = "REPLACE_ME_GEMINI_NOTES_FOLDER_ID"

PATCH_JS = r"""
const { DatabaseSync } = require("node:sqlite");
const fs = require("fs");
const crypto = require("crypto");
const srcPath = process.env.SAVE5HOURS_WF_SRC || "/tmp/save5hours-meeting-notes.json";
const wfName = "Meeting notes → HQ Tasks";
const placeholder = "REPLACE_ME_GEMINI_NOTES_FOLDER_ID";
const paths = ["/home/node/.n8n/.n8n/database.sqlite", "/home/node/.n8n/database.sqlite"];
const src = JSON.parse(fs.readFileSync(srcPath, "utf8"));

function openLive() {
  let best = null;
  let bestActive = -1;
  for (const p of paths) {
    if (!fs.existsSync(p)) continue;
    const db = new DatabaseSync(p);
    let active = 0;
    try {
      active = Number(db.prepare("SELECT COUNT(*) AS n FROM workflow_entity WHERE active = 1").get()?.n || 0);
    } catch (err) {
      db.close();
      continue;
    }
    if (active > bestActive) {
      if (best) best.db.close();
      best = { path: p, db };
      bestActive = active;
    } else {
      db.close();
    }
  }
  if (!best) throw new Error("no sqlite database");
  return best;
}

function credsFromNodes(nodes) {
  const ids = {};
  for (const node of nodes || []) {
    for (const spec of Object.values(node.credentials || {})) {
      const name = String(spec?.name || "");
      if (name && spec.id && spec.id !== "GOOGLE_DRIVE" && spec.id !== "REPLACE_ME") {
        ids[name] = { id: spec.id, name };
      }
    }
  }
  return ids;
}

const { path, db } = openLive();
const row =
  db.prepare("SELECT id, name, active, nodes FROM workflow_entity WHERE name = ? ORDER BY active DESC LIMIT 1").get(wfName)
  || db.prepare("SELECT id, name, active, nodes FROM workflow_entity WHERE id = ? LIMIT 1").get(src.id);
if (!row?.id) {
  db.close();
  throw new Error("workflow row missing");
}
const liveCreds = credsFromNodes(JSON.parse(row.nodes || "[]"));
const folder = String(process.env.GEMINI_NOTES_FOLDER_ID || "").trim();
const googleReady = Boolean(liveCreds["Google Drive (Save 5 Hours)"] && folder && folder !== placeholder);
const nodes = JSON.parse(JSON.stringify(src.nodes || []));
for (const node of nodes) {
  for (const spec of Object.values(node.credentials || {})) {
    const mapped = liveCreds[String(spec?.name || "")];
    if (mapped) {
      spec.id = mapped.id;
      spec.name = mapped.name;
    }
  }
  if (node.type === "n8n-nodes-base.googleDriveTrigger") {
    if (googleReady) {
      node.disabled = false;
      if (node.parameters?.folderToWatch) node.parameters.folderToWatch.value = folder;
    } else {
      node.disabled = true;
    }
  }
}
const now = new Date().toISOString().replace("T", " ").replace("Z", "");
db.prepare(
  `UPDATE workflow_entity
   SET nodes = ?, connections = ?, versionId = ?, updatedAt = ?,
       name = ?, active = 1
   WHERE id = ?`
).run(
  JSON.stringify(nodes),
  JSON.stringify(src.connections || {}),
  crypto.randomUUID(),
  now,
  wfName,
  row.id,
);
try { db.prepare("PRAGMA wal_checkpoint(TRUNCATE)").run(); } catch {}
const after = db.prepare("SELECT id, name, active FROM workflow_entity WHERE id = ?").get(row.id);
db.close();
process.stdout.write(JSON.stringify({
  ok: true,
  db: path,
  id: after.id,
  name: after.name,
  active: Number(after.active) === 1,
  nodeCount: nodes.length,
  driveEnabled: googleReady,
  reusedCredentials: Object.keys(liveCreds).sort(),
}));
"""


def railway_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("RAILWAY_CALLER", "skill:use-railway@1.3.7")
    env["PATH"] = os.path.expanduser("~/.npm-global/bin") + os.pathsep + env.get("PATH", "")
    return env


def run(cmd: list[str], *, timeout: int = 90, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd[:8]), ("..." if len(cmd) > 8 else ""), flush=True)
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=railway_env(),
        input=stdin,
    )


def railway_scope() -> list[str]:
    return ["--project", PROJECT, "--environment", ENV, "--service", SERVICE]


def whoami() -> bool:
    proc = run(["railway", "whoami"], timeout=30)
    if proc.returncode != 0:
        print("railway not logged in", flush=True)
        if proc.stderr:
            print(proc.stderr.strip()[:300], flush=True)
        return False
    print("railway whoami:", (proc.stdout or "").strip()[:120], flush=True)
    return True


def railway_vars() -> dict[str, str]:
    proc = run(["railway", "variables", *railway_scope(), "--json"], timeout=45)
    if proc.returncode != 0:
        print("railway variables failed:", (proc.stderr or proc.stdout)[:300], flush=True)
        return {}
    data = json.loads(proc.stdout or "{}")
    return {str(k): str(v) if v is not None else "" for k, v in data.items()} if isinstance(data, dict) else {}


def wait_health(seconds: int = 180) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{N8N_URL}/healthz", timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200 and "ok" in body.lower():
                    print("healthz ok", flush=True)
                    return True
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(4)
    print("healthz timeout", flush=True)
    return False


def upload_and_patch(folder: str) -> dict:
    src = WF_SRC.read_text(encoding="utf-8")
    json.loads(src)  # validate
    remote_json = "/tmp/save5hours-meeting-notes.json"
    remote_js = "/tmp/save5hours-patch-workflow.js"
    put_json = run(
        ["railway", "ssh", *railway_scope(), "--", f"cat > {remote_json}"],
        timeout=90,
        stdin=src,
    )
    if put_json.returncode != 0:
        raise SystemExit(f"upload workflow json failed: {(put_json.stderr or put_json.stdout)[:500]}")
    put_js = run(
        ["railway", "ssh", *railway_scope(), "--", f"cat > {remote_js}"],
        timeout=60,
        stdin=PATCH_JS,
    )
    if put_js.returncode != 0:
        raise SystemExit(f"upload patch script failed: {(put_js.stderr or put_js.stdout)[:500]}")
    env_prefix = f"SAVE5HOURS_WF_SRC={remote_json}"
    if folder:
        env_prefix += f" GEMINI_NOTES_FOLDER_ID={folder}"
    proc = run(
        [
            "railway",
            "ssh",
            *railway_scope(),
            "--",
            f"if [ -x /usr/sbin/gosu ] || command -v gosu >/dev/null; then gosu node env {env_prefix} node {remote_js}; "
            f"else env HOME=/home/node N8N_USER_FOLDER=/home/node/.n8n {env_prefix} node {remote_js}; fi",
        ],
        timeout=90,
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    start = text.find("{")
    end = text.rfind("}")
    if proc.returncode != 0 or start == -1:
        raise SystemExit(f"sqlite patch failed: {text[:800]}")
    payload = json.loads(text[start : end + 1])
    print(
        f"patched workflow {payload.get('id')} nodes={payload.get('nodeCount')} "
        f"active={payload.get('active')} creds={payload.get('reusedCredentials')}",
        flush=True,
    )
    return payload


def restart_n8n() -> None:
    proc = run(["railway", "restart", *railway_scope(), "--yes"], timeout=90)
    if proc.returncode != 0:
        print("railway restart failed; trying redeploy", flush=True)
        proc = run(["railway", "redeploy", *railway_scope(), "--yes"], timeout=90)
        if proc.returncode != 0:
            raise SystemExit(f"restart/redeploy failed: {(proc.stderr or proc.stdout)[:400]}")
    if not wait_health():
        raise SystemExit("n8n did not become healthy after restart")


def main() -> int:
    if not whoami():
        return 2
    vars_ = railway_vars()
    folder = (vars_.get("GEMINI_NOTES_FOLDER_ID") or "").strip()
    print("n8n SSH publish (secrets redacted)")
    print(f"  GEMINI_NOTES_FOLDER_ID: {'yes' if folder else 'NO (Drive triggers stay disabled)'}")
    payload = upload_and_patch(folder)
    restart_n8n()
    print(f"live canvas replaced: {payload.get('nodeCount')} nodes, id={payload.get('id')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

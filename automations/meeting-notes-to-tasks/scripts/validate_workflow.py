#!/usr/bin/env python3
"""Sanity-check the n8n workflow JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "n8n" / "meeting-notes-to-tasks.json"
data = json.loads(path.read_text(encoding="utf-8"))

nodes = {n["name"]: n for n in data["nodes"]}
required = [
    "Google Drive Trigger",
    "Google Drive Trigger (updated)",
    "Webhook",
    "Manual test",
    "Set test fileId",
    "Normalize file",
    "Has inline notes",
    "Use inline notes",
    "Notes have content",
    "OpenRouter",
    "Parse and map assignees",
    "Create Notion task",
]
missing = [name for name in required if name not in nodes]
if missing:
    raise SystemExit(f"missing nodes: {missing}")

node_names = set(nodes)
for src, spec in data["connections"].items():
    if src not in node_names:
        raise SystemExit(f"connection source missing: {src}")
    for branch in spec.get("main", []):
        for link in branch or []:
            if link["node"] not in node_names:
                raise SystemExit(f"connection target missing: {link['node']}")

created = nodes["Google Drive Trigger"]["parameters"]["event"]
updated = nodes["Google Drive Trigger (updated)"]["parameters"]["event"]
if created != "fileCreated" or updated != "fileUpdated":
    raise SystemExit(f"unexpected Drive events: {created} {updated}")

conns = data["connections"]
assert "Google Drive Trigger" in conns
assert "Webhook" in conns
assert conns["Normalize file"]["main"][0][0]["node"] == "Has inline notes"
assert conns["Has inline notes"]["main"][0][0]["node"] == "Use inline notes"
assert conns["Has inline notes"]["main"][1][0]["node"] == "Only Google Docs"
assert conns["Use inline notes"]["main"][0][0]["node"] == "Notes have content"
assert conns["Build Notion page"]["main"][0][0]["node"] == "Create Notion task"

parse = nodes["Parse and map assignees"]["parameters"]["jsCode"]
for user_id in (
    "3bcd872b-594c-8157-a68b-0002ec224796",
    "3bcd872b-594c-81b9-acfe-0002ebe41550",
    "3bcd872b-594c-81a9-bf7d-00029eb21064",
):
    if user_id not in parse:
        raise SystemExit(f"assignee id missing from parse node: {user_id}")

create_url = nodes["Create Notion task"]["parameters"]["url"]
assert create_url == "https://api.notion.com/v1/pages"

or_url = nodes["OpenRouter"]["parameters"]["url"]
assert or_url == "https://openrouter.ai/api/v1/chat/completions"

folder = nodes["Google Drive Trigger"]["parameters"]["folderToWatch"]["value"]
assert folder == "REPLACE_ME_GEMINI_NOTES_FOLDER_ID"

print(f"ok: {len(nodes)} nodes, {len(conns)} connection sources, {path}")
sys.exit(0)

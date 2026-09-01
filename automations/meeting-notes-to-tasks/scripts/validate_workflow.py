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
    "Drive Apps Script",
    "Extract Google token",
    "Google userinfo",
    "Allow Drive caller",
    "Public Drive Doc",
    "Public Drive Doc GET",
    "Drive Apps Script GET",
    "Redirect to Drive setup",
    "Parse Drive URL",
    "Has Drive file ID",
    "Respond public Doc",
    "Respond public Doc error",
    "Reject missing Drive URL",
    "Has Doc text already",
    "Export public Doc",
    "Merge public Doc",
    "Export usable",
    "Public webhook ack",
    "HQ Drive URL poll",
    "Fetch HQ Drive confirmation",
    "Fetch HQ Drive blocks",
    "Fetch HQ Drive comments",
    "Find HQ Drive URL rows",
    "Expand HQ Tasks",
    "Fetch HQ Task comments",
    "Fetch HQ Task blocks",
    "Merge HQ Task extras",
    "Parse HQ Drive confirmation",
    "Find HQ Drive duplicates",
    "Skip imported HQ Drive",
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
assert conns["Drive Apps Script"]["main"][0][0]["node"] == "Extract Google token"
assert conns["Extract Google token"]["main"][0][0]["node"] == "Google userinfo"
assert conns["Google userinfo"]["main"][0][0]["node"] == "Allow Drive caller"
assert conns["Allow Drive caller"]["main"][0][0]["node"] == "Normalize file"
assert conns["Public Drive Doc"]["main"][0][0]["node"] == "Parse Drive URL"
assert nodes["Public Drive Doc GET"]["parameters"]["httpMethod"] == "GET"
assert nodes["Public Drive Doc GET"]["parameters"]["path"] == "public-drive-doc"
assert nodes["Drive Apps Script GET"]["parameters"]["httpMethod"] == "GET"
assert nodes["Drive Apps Script GET"]["parameters"]["path"] == "meeting-notes-drive"
assert conns["Public Drive Doc GET"]["main"][0][0]["node"] == "Redirect to Drive setup"
assert conns["Drive Apps Script GET"]["main"][0][0]["node"] == "Redirect to Drive setup"
assert "/webhook/drive-setup" in nodes["Redirect to Drive setup"]["parameters"]["responseBody"]
assert conns["Parse Drive URL"]["main"][0][0]["node"] == "Has Drive file ID"
true_nodes = [link["node"] for link in conns["Has Drive file ID"]["main"][0]]
assert true_nodes == ["Has Doc text already"]
assert conns["Has Drive file ID"]["main"][1][0]["node"] == "Respond public Doc error"
assert "Respond public Doc" not in conns
assert conns["Respond public Doc error"]["main"][0][0]["node"] == "Reject missing Drive URL"
assert nodes["Respond public Doc error"]["parameters"]["options"]["responseCode"] == 400
assert nodes["Public Drive Doc"]["parameters"]["responseMode"] == "responseNode"
assert conns["Has Doc text already"]["main"][0][0]["node"] == "Public webhook ack"
assert conns["Has Doc text already"]["main"][1][0]["node"] == "Export public Doc"
assert conns["Export public Doc"]["main"][0][0]["node"] == "Merge public Doc"
assert conns["Merge public Doc"]["main"][0][0]["node"] == "Export usable"
assert conns["Export usable"]["main"][0][0]["node"] == "Public webhook ack"
assert conns["Export usable"]["main"][1][0]["node"] == "Respond public Doc error"
ack_true = [link["node"] for link in conns["Public webhook ack"]["main"][0]]
assert ack_true == ["Respond public Doc", "Normalize file"]
assert conns["Public webhook ack"]["main"][1][0]["node"] == "Normalize file"
assert nodes["Export public Doc"].get("continueOnFail") is True
assert conns["HQ Drive URL poll"]["main"][0][0]["node"] == "Fetch HQ Drive confirmation"
assert conns["Fetch HQ Drive confirmation"]["main"][0][0]["node"] == "Fetch HQ Drive blocks"
assert conns["Fetch HQ Drive blocks"]["main"][0][0]["node"] == "Fetch HQ Drive comments"
assert conns["Fetch HQ Drive comments"]["main"][0][0]["node"] == "Find HQ Drive URL rows"
assert conns["Find HQ Drive URL rows"]["main"][0][0]["node"] == "Expand HQ Tasks"
assert conns["Expand HQ Tasks"]["main"][0][0]["node"] == "Fetch HQ Task comments"
assert conns["Expand HQ Tasks"]["main"][0][1]["node"] == "Fetch HQ Task blocks"
assert conns["Fetch HQ Task comments"]["main"][0][0]["node"] == "Merge HQ Task extras"
assert conns["Fetch HQ Task blocks"]["main"][0][0]["node"] == "Merge HQ Task extras"
assert conns["Fetch HQ Task blocks"]["main"][0][0]["index"] == 1
assert conns["Merge HQ Task extras"]["main"][0][0]["node"] == "Parse HQ Drive confirmation"
assert conns["Parse HQ Drive confirmation"]["main"][0][0]["node"] == "Find HQ Drive duplicates"
assert conns["Find HQ Drive duplicates"]["main"][0][0]["node"] == "Skip imported HQ Drive"
assert conns["Skip imported HQ Drive"]["main"][0][0]["node"] == "Has Doc text already"
hq_parse = nodes["Parse HQ Drive confirmation"]["parameters"]["jsCode"]
if "parseHqDriveConfirmation" not in hq_parse:
    raise SystemExit("Parse HQ Drive confirmation must use parseHqDriveConfirmation")
if "pickHqDrivePayload" not in hq_parse:
    raise SystemExit("Parse HQ Drive confirmation must use pickHqDrivePayload")
if "hqPastedNotes" not in hq_parse:
    raise SystemExit("Parse HQ Drive confirmation must use pasted HQ notes (hqPastedNotes)")
if "Fetch HQ Task comments" not in hq_parse:
    raise SystemExit("Parse HQ Drive confirmation must merge comments from every HQ Task")
if "Fetch HQ Task blocks" not in hq_parse:
    raise SystemExit("Parse HQ Drive confirmation must merge bodies from every HQ Task")
merge_public = nodes["Merge public Doc"]["parameters"]["jsCode"]
if "Parse HQ Drive confirmation" not in merge_public:
    raise SystemExit("Merge public Doc must read Parse HQ Drive confirmation meta")
if "publicExportLooksLikeHtml" not in merge_public:
    raise SystemExit("Merge public Doc must reject HTML export bodies")
if "fromPublicWebhook" not in merge_public:
    raise SystemExit("Merge public Doc must keep public-webhook export failures off HQ poll")
if "exportFailed" not in merge_public:
    raise SystemExit("Merge public Doc must flag failed public exports")
assert nodes["Public Drive Doc"]["parameters"]["path"] == "public-drive-doc"
parse_public = nodes["Parse Drive URL"]["parameters"]["jsCode"]
if "extractPublicDrivePayload" not in parse_public:
    raise SystemExit("Parse Drive URL must use extractPublicDrivePayload")
if "fromPublicWebhook" not in parse_public:
    raise SystemExit("Parse Drive URL must mark public webhook items")
if r"docs\.google\.com\/open\?id=" not in parse_public:
    raise SystemExit("Parse Drive URL must accept Apps Script docs.google.com/open?id= URLs")
assert nodes["Drive Apps Script"]["parameters"]["path"] == "meeting-notes-drive"
assert nodes["Webhook"]["parameters"]["authentication"] == "headerAuth"
assert "authentication" not in nodes["Drive Apps Script"]["parameters"] or not nodes["Drive Apps Script"]["parameters"].get("authentication")
allow = nodes["Allow Drive caller"]["parameters"]["jsCode"]
if "driveCallerAllowed" not in allow:
    raise SystemExit("Allow Drive caller must check driveCallerAllowed")
userinfo = nodes["Google userinfo"]["parameters"]["url"]
assert userinfo == "https://www.googleapis.com/oauth2/v2/userinfo"
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

build_code = nodes["Build Notion page"]["parameters"]["jsCode"]
if "$input.all()" not in build_code:
    raise SystemExit("Build Notion page must map every split task, not only $input.first()")

or_url = nodes["OpenRouter"]["parameters"]["url"]
assert or_url == "https://openrouter.ai/api/v1/chat/completions"

folder = nodes["Google Drive Trigger"]["parameters"]["folderToWatch"]["value"]
assert folder == "REPLACE_ME_GEMINI_NOTES_FOLDER_ID"

print(f"ok: {len(nodes)} nodes, {len(conns)} connection sources, {path}")
sys.exit(0)

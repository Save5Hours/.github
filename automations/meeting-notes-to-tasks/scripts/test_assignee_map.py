#!/usr/bin/env python3
"""Check assignee-map.json matches the workflow parse node."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
mapping = json.loads((ROOT / "config" / "assignee-map.json").read_text(encoding="utf-8"))
workflow = json.loads((ROOT / "n8n" / "meeting-notes-to-tasks.json").read_text(encoding="utf-8"))
parse = next(n for n in workflow["nodes"] if n["name"] == "Parse and map assignees")
code = parse["parameters"]["jsCode"]

for key, person in mapping["people"].items():
    uid = person["notionUserId"]
    if uid not in code:
        raise SystemExit(f"{key} Notion id missing from workflow: {uid}")
    for alias in person["aliases"]:
        if alias == key:
            continue
        if f"'{alias}'" not in code and f'"{alias}"' not in code:
            raise SystemExit(f"alias {alias!r} missing from workflow")

assert mapping["defaultAssignee"] == "antoine"
print("assignee map ok")

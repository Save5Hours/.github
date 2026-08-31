#!/usr/bin/env python3
"""Generate the importable n8n workflow JSON."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_DB = "3bc0b26fcc4e8057b7ade1cdf5a67e6e"
ANTOINE = "3bcd872b-594c-8157-a68b-0002ec224796"
MARTIN = "3bcd872b-594c-81b9-acfe-0002ebe41550"
ROMAN = "3bcd872b-594c-81a9-bf7d-00029eb21064"
DRIVE_FOLDER_PLACEHOLDER = "REPLACE_ME_GEMINI_NOTES_FOLDER_ID"
GOOGLE_CREDS = {
    "googleDriveOAuth2Api": {
        "id": "GOOGLE_DRIVE",
        "name": "Google Drive (Save 5 Hours)",
    }
}
NOTION_CREDS = {
    "notionApi": {
        "id": "NOTION",
        "name": "Notion (Save 5 Hours HQ)",
    }
}


def n8n_inline_mjs(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return (
        text.replace("export const ", "const ")
        .replace("export function ", "function ")
        .strip()
    )


TRANSFORM_JS = n8n_inline_mjs(ROOT / "lib" / "transform.mjs")

NORMALIZE_CODE = TRANSFORM_JS + "\n\n" + r"""
const item = $input.first().json || {};
return [{ json: normalizeMeetingInput(item) }];
""".strip()

BUILD_OPENROUTER_CODE = r"""
const text = ($json.data || $json.text || '').toString().slice(0, 24000);
const fileName = $('Normalize file').first().json.name || 'Untitled meeting notes';
const fileId = $('Normalize file').first().json.fileId;
const webViewLink = $('Normalize file').first().json.webViewLink;

const system = `You extract action items from Google Meet / Gemini notes for Save 5 Hours.

Return ONLY valid JSON (no markdown) with this shape:
{
  "meeting_title": "string",
  "tasks": [
    {
      "title": "short imperative task in English",
      "assignee": "antoine" | "martin" | "roman",
      "priority": "High" | "Medium" | "Low",
      "due": "YYYY-MM-DD" or null,
      "notes": "one-sentence context"
    }
  ]
}

Team mapping (use these keys, not other names):
- antoine = Antoine Bejarano Alvarez, antoine@save5hours.ch
- martin = Martin, martin@save5hours.ch
- roman = Roman Cajka, roman@save5hours.ch, also Ronald / Roman Cajka Gmail

Rules:
- Only create real action items (someone will do something). Skip recap-only sentences.
- If the owner is unclear, set assignee to "antoine".
- Titles in English, max 80 characters, start with a verb.
- Prefer one task per person per action. Split "Antoine brings beers and Martin brings cheese" into two tasks.
- If there are no action items, return {"meeting_title": "...", "tasks": []}.`;

const user = `Meeting document title: ${fileName}\n\nNotes:\n${text || '(empty document)'}`;

return [{
  json: {
    fileId,
    fileName,
    webViewLink,
    text,
    openRouterBody: {
      model: 'openrouter/free',
      temperature: 0.1,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
    },
  },
}];
""".strip()

PARSE_CODE = TRANSFORM_JS + "\n\n" + """
const http = $input.first().json;
const content = http.choices?.[0]?.message?.content || http.content || '';
const meta = $('Build OpenRouter payload').first().json;
const parsed = parseOpenRouterContent(content, meta);
parsed.model = http.model || 'openrouter/free';
return [{ json: parsed }];
""".strip()

SKIP_DUPES_CODE = TRANSFORM_JS + "\n\n" + """
const parsed = $('Parse and map assignees').first().json;
const query = $input.first().json || {};
return [{ json: skipDuplicateTasks(parsed, query) }];
""".strip()

BUILD_NOTION_CODE = TRANSFORM_JS + "\n\n" + """
return [{ json: buildNotionPage($input.first().json) }];
""".strip()

NOTION_FILTER_BODY = (
    "={{ JSON.stringify({ filter: { property: 'Drive file ID', rich_text: "
    "{ equals: $json.driveFileId } }, page_size: 100 }) }}"
)

nodes = [
    {
        "id": "note-overview",
        "name": "How this workflow runs",
        "type": "n8n-nodes-base.stickyNote",
        "typeVersion": 1,
        "position": [-420, 140],
        "parameters": {
            "content": "## Meeting notes → HQ Tasks\n\nGemini often creates an empty Doc and fills it after the meeting. This workflow watches **file created** and **file updated**, skips notes shorter than 80 characters, then sends text to OpenRouter (`openrouter/free`) and writes HQ Tasks.\n\n**Host n8n 1.123.x** (this repo Dockerfile). n8n 2.x needs extra task runners for Code nodes.\n\nSet `GEMINI_NOTES_FOLDER_ID` in Railway (or replace both Drive folder IDs). Webhook can send `{ \"fileId\" }` or `{ \"text\" }` for a dry run. Connect Google Drive, Notion, OpenRouter, and the webhook secret.",
            "height": 380,
            "width": 340,
            "color": 7,
        },
    },
    {
        "id": "drive-trigger",
        "name": "Google Drive Trigger",
        "type": "n8n-nodes-base.googleDriveTrigger",
        "typeVersion": 1,
        "position": [0, 200],
        "parameters": {
            "pollTimes": {"item": [{"mode": "everyMinute"}]},
            "triggerOn": "specificFolder",
            "folderToWatch": {
                "__rl": True,
                "value": DRIVE_FOLDER_PLACEHOLDER,
                "mode": "id",
            },
            "event": "fileCreated",
            "options": {"fileType": "application/vnd.google-apps.document"},
        },
        "credentials": GOOGLE_CREDS,
    },
    {
        "id": "drive-trigger-updated",
        "name": "Google Drive Trigger (updated)",
        "type": "n8n-nodes-base.googleDriveTrigger",
        "typeVersion": 1,
        "position": [0, 40],
        "parameters": {
            "pollTimes": {"item": [{"mode": "everyMinute"}]},
            "triggerOn": "specificFolder",
            "folderToWatch": {
                "__rl": True,
                "value": DRIVE_FOLDER_PLACEHOLDER,
                "mode": "id",
            },
            "event": "fileUpdated",
            "options": {"fileType": "application/vnd.google-apps.document"},
        },
        "credentials": GOOGLE_CREDS,
    },
    {
        "id": "manual-trigger",
        "name": "Manual test",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": [0, 680],
        "parameters": {},
    },
    {
        "id": "set-test-file",
        "name": "Set test fileId",
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [220, 680],
        "parameters": {
            "mode": "manual",
            "duplicateItem": False,
            "assignments": {
                "assignments": [
                    {
                        "id": "file-id",
                        "name": "fileId",
                        "value": "REPLACE_ME_GOOGLE_DOC_FILE_ID",
                        "type": "string",
                    }
                ]
            },
            "options": {},
        },
    },
    {
        "id": "webhook",
        "name": "Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 460],
        "webhookId": "meeting-notes",
        "parameters": {
            "httpMethod": "POST",
            "path": "meeting-notes",
            "authentication": "headerAuth",
            "responseMode": "onReceived",
            "options": {},
        },
        "credentials": {
            "httpHeaderAuth": {
                "id": "WEBHOOK_SECRET",
                "name": "Meeting notes webhook secret",
            }
        },
    },
    {
        "id": "normalize",
        "name": "Normalize file",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [280, 320],
        "parameters": {"jsCode": NORMALIZE_CODE},
    },
    {
        "id": "has-inline",
        "name": "Has inline notes",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [500, 320],
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": "inline-ok",
                        "leftValue": "={{ $json.inlineText }}",
                        "rightValue": "",
                        "operator": {
                            "type": "string",
                            "operation": "notEmpty",
                            "singleValue": True,
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    },
    {
        "id": "use-inline",
        "name": "Use inline notes",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [740, 140],
        "parameters": {
            "jsCode": (
                "const src = $input.first().json || {};\n"
                "return [{ json: { ...src, data: src.inlineText || src.text || '' } }];"
            ),
        },
    },
    {
        "id": "only-docs",
        "name": "Only Google Docs",
        "type": "n8n-nodes-base.filter",
        "typeVersion": 2.2,
        "position": [500, 520],
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": "mime-ok",
                        "leftValue": "={{ $json.mimeType }}",
                        "rightValue": "application/vnd.google-apps.document",
                        "operator": {
                            "type": "string",
                            "operation": "equals",
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    },
    {
        "id": "download",
        "name": "Download Google Doc as text",
        "type": "n8n-nodes-base.googleDrive",
        "typeVersion": 3,
        "position": [740, 520],
        "parameters": {
            "operation": "download",
            "fileId": {
                "__rl": True,
                "value": "={{ $json.fileId }}",
                "mode": "id",
            },
            "options": {
                "googleFileConversion": {"docsToFormat": "text/plain"},
            },
        },
        "credentials": GOOGLE_CREDS,
    },
    {
        "id": "extract",
        "name": "Extract from File",
        "type": "n8n-nodes-base.extractFromFile",
        "typeVersion": 1,
        "position": [980, 520],
        "parameters": {"operation": "text", "options": {}},
    },
    {
        "id": "has-content",
        "name": "Notes have content",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1100, 320],
        "parameters": {
            "jsCode": TRANSFORM_JS
            + "\n\n"
            + """
const item = $input.first();
const text = (item.json.data || item.json.text || '').toString();
if (!noteTextIsReady(text)) {
  return [];
}
return [item];
""".strip()
        },
    },
    {
        "id": "build-or",
        "name": "Build OpenRouter payload",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1220, 320],
        "parameters": {"jsCode": BUILD_OPENROUTER_CODE},
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1460, 320],
        "parameters": {
            "method": "POST",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "HTTP-Referer", "value": "https://save5hours.ch"},
                    {"name": "X-Title", "value": "Save 5 Hours meeting notes"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.openRouterBody) }}",
            "options": {"timeout": 120000, "response": {"response": {"fullResponse": False}}},
        },
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 3000,
        "credentials": {
            "httpHeaderAuth": {
                "id": "OPENROUTER",
                "name": "OpenRouter",
            }
        },
    },
    {
        "id": "parse",
        "name": "Parse and map assignees",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1700, 320],
        "parameters": {"jsCode": PARSE_CODE},
    },
    {
        "id": "has-tasks",
        "name": "Has tasks",
        "type": "n8n-nodes-base.filter",
        "typeVersion": 2.2,
        "position": [1940, 320],
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": "count-gt-0",
                        "leftValue": "={{ $json.taskCount }}",
                        "rightValue": 0,
                        "operator": {
                            "type": "number",
                            "operation": "gt",
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    },
    {
        "id": "find-existing",
        "name": "Find existing tasks",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [2180, 320],
        "alwaysOutputData": True,
        "parameters": {
            "method": "POST",
            "url": f"https://api.notion.com/v1/databases/{TASKS_DB}/query",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": NOTION_FILTER_BODY,
            "options": {},
        },
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "skip-dupes",
        "name": "Skip duplicates",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [2420, 320],
        "parameters": {
            "mode": "runOnceForAllItems",
            "jsCode": SKIP_DUPES_CODE,
        },
    },
    {
        "id": "has-new",
        "name": "Has new tasks",
        "type": "n8n-nodes-base.filter",
        "typeVersion": 2.2,
        "position": [2660, 320],
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": "new-gt-0",
                        "leftValue": "={{ $json.taskCount }}",
                        "rightValue": 0,
                        "operator": {
                            "type": "number",
                            "operation": "gt",
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    },
    {
        "id": "split",
        "name": "Split tasks",
        "type": "n8n-nodes-base.splitOut",
        "typeVersion": 1,
        "position": [2900, 320],
        "parameters": {"fieldToSplitOut": "tasks", "options": {}},
    },
    {
        "id": "build-notion",
        "name": "Build Notion page",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [3140, 320],
        "parameters": {"jsCode": BUILD_NOTION_CODE},
    },
    {
        "id": "create-notion",
        "name": "Create Notion task",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [3380, 320],
        "parameters": {
            "method": "POST",
            "url": "https://api.notion.com/v1/pages",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json) }}",
            "options": {},
        },
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
]


def conn(*names: str) -> dict:
    return {
        "main": [[{"node": name, "type": "main", "index": 0} for name in names]]
    }


connections = {
    "Google Drive Trigger": conn("Normalize file"),
    "Google Drive Trigger (updated)": conn("Normalize file"),
    "Webhook": conn("Normalize file"),
    "Manual test": conn("Set test fileId"),
    "Set test fileId": conn("Normalize file"),
    "Normalize file": conn("Has inline notes"),
    "Has inline notes": {
        "main": [
            [{"node": "Use inline notes", "type": "main", "index": 0}],
            [{"node": "Only Google Docs", "type": "main", "index": 0}],
        ]
    },
    "Use inline notes": conn("Notes have content"),
    "Only Google Docs": conn("Download Google Doc as text"),
    "Download Google Doc as text": conn("Extract from File"),
    "Extract from File": conn("Notes have content"),
    "Notes have content": conn("Build OpenRouter payload"),
    "Build OpenRouter payload": conn("OpenRouter"),
    "OpenRouter": conn("Parse and map assignees"),
    "Parse and map assignees": conn("Has tasks"),
    "Has tasks": conn("Find existing tasks"),
    "Find existing tasks": conn("Skip duplicates"),
    "Skip duplicates": conn("Has new tasks"),
    "Has new tasks": conn("Split tasks"),
    "Split tasks": conn("Build Notion page"),
    "Build Notion page": conn("Create Notion task"),
}

workflow = {
    "id": "KfrQb6c79aJPPxYE",
    "name": "Meeting notes → HQ Tasks",
    "nodes": nodes,
    "connections": connections,
    "active": False,
    "settings": {
        "executionOrder": "v1",
        "availableInMCP": False,
        "callerPolicy": "workflowsFromSameOwner",
        "errorWorkflow": "",
    },
    "pinData": {},
    "meta": {
        "templateCredsSetupCompleted": False,
        "description": "Gemini / Google Meet notes in Drive → OpenRouter → Notion HQ Tasks",
    },
}

out = Path(__file__).resolve().parents[1] / "n8n" / "meeting-notes-to-tasks.json"
out.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {out}")


if __name__ == "__main__":
    pass

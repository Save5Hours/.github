#!/usr/bin/env python3
"""Generate the importable n8n workflow JSON."""

from __future__ import annotations

import json
from pathlib import Path

TASKS_DB = "3bc0b26fcc4e8057b7ade1cdf5a67e6e"
ANTOINE = "3bcd872b-594c-8157-a68b-0002ec224796"
MARTIN = "3bcd872b-594c-81b9-acfe-0002ebe41550"
ROMAN = "3bcd872b-594c-81a9-bf7d-00029eb21064"

NORMALIZE_CODE = r"""
const item = $input.first().json || {};
const body = item.body && typeof item.body === 'object' ? item.body : {};

const fileId = item.id || item.fileId || body.id || body.fileId;
if (!fileId) {
  throw new Error('Missing Google Drive fileId. Drive Trigger should send file.id; webhook body must be { "fileId": "..." }.');
}

const mimeType = item.mimeType || body.mimeType || 'application/vnd.google-apps.document';
const name = item.name || body.name || '';
const webViewLink = item.webViewLink || body.webViewLink || `https://drive.google.com/file/d/${fileId}/view`;

return [{
  json: {
    fileId,
    name,
    mimeType,
    webViewLink,
  },
}];
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

PARSE_CODE = r'''
const PEOPLE = {
  antoine: "''' + ANTOINE + r'''",
  martin: "''' + MARTIN + r'''",
  roman: "''' + ROMAN + r'''",
};

const ALIASES = {
  'antoine': 'antoine',
  'antoine bejarano': 'antoine',
  'antoine bejarano alvarez': 'antoine',
  'antoine@save5hours.ch': 'antoine',
  'martin': 'martin',
  'martin@save5hours.ch': 'martin',
  'roman': 'roman',
  'ronald': 'roman',
  'roman cajka': 'roman',
  'roman@save5hours.ch': 'roman',
  'roman.cajka@gmail.com': 'roman',
};

function extractJson(text) {
  const raw = String(text || '');
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1] : raw;
  const start = body.indexOf('{');
  const end = body.lastIndexOf('}');
  if (start === -1 || end === -1) {
    throw new Error(`OpenRouter did not return JSON. Preview: ${raw.slice(0, 400)}`);
  }
  return JSON.parse(body.slice(start, end + 1));
}

function mapAssignee(value) {
  const key = String(value || '').trim().toLowerCase();
  const mapped = ALIASES[key] || (PEOPLE[key] ? key : 'antoine');
  return { key: mapped, id: PEOPLE[mapped] };
}

function mapPriority(value) {
  const p = String(value || 'Medium');
  if (p === 'High' || p === 'Low' || p === 'Medium') return p;
  const lower = p.toLowerCase();
  if (lower.includes('high') || lower.includes('urgent')) return 'High';
  if (lower.includes('low')) return 'Low';
  return 'Medium';
}

const http = $input.first().json;
const content = http.choices?.[0]?.message?.content || http.content || '';
const parsed = extractJson(content);
const meta = $('Build OpenRouter payload').first().json;

const tasks = (parsed.tasks || []).map((task) => {
  const person = mapAssignee(task.assignee);
  const title = String(task.title || '').replace(/\s+/g, ' ').trim();
  const due = task.due && /^\d{4}-\d{2}-\d{2}/.test(String(task.due))
    ? String(task.due).slice(0, 10)
    : null;
  return {
    title,
    assignee: person.key,
    assigneeId: person.id,
    priority: mapPriority(task.priority),
    due,
    notes: String(task.notes || '').trim(),
    meetingTitle: parsed.meeting_title || meta.fileName,
    driveFileId: meta.fileId,
    driveUrl: meta.webViewLink,
  };
}).filter((task) => task.title.length > 0);

return [{
  json: {
    meetingTitle: parsed.meeting_title || meta.fileName,
    driveFileId: meta.fileId,
    driveUrl: meta.webViewLink,
    model: http.model || 'openrouter/free',
    taskCount: tasks.length,
    tasks,
  },
}];
'''.strip()

SKIP_DUPES_CODE = r"""
const parsed = $('Parse and map assignees').first().json;
const query = $input.first().json || {};
const results = Array.isArray(query.results) ? query.results : [];

const existingTitles = new Set(
  results.map((page) => {
    const title = page.properties?.Name?.title?.[0]?.plain_text || '';
    return title.trim().toLowerCase();
  }).filter(Boolean),
);

const tasks = (parsed.tasks || []).filter((task) => {
  return !existingTitles.has(String(task.title).trim().toLowerCase());
});

return [{
  json: {
    ...parsed,
    existingCount: existingTitles.size,
    skipped: (parsed.tasks || []).length - tasks.length,
    taskCount: tasks.length,
    tasks,
  },
}];
""".strip()

BUILD_NOTION_CODE = r"""
const t = $input.first().json;
const title = String(t.title || 'Untitled task').slice(0, 2000);
const properties = {
  Name: { title: [{ text: { content: title } }] },
  Assignee: { people: t.assigneeId ? [{ id: t.assigneeId }] : [] },
  Status: { status: { name: 'Not started' } },
  Priority: { select: { name: t.priority || 'Medium' } },
  Origin: { select: { name: 'Meeting' } },
  'Drive file ID': { rich_text: [{ text: { content: t.driveFileId || '' } }] },
  'Drive URL': { url: t.driveUrl || null },
};

if (t.due) {
  properties['Due date'] = { date: { start: t.due } };
}

const children = [];
if (t.meetingTitle) {
  children.push({
    object: 'block',
    type: 'paragraph',
    paragraph: {
      rich_text: [{ type: 'text', text: { content: `From meeting: ${String(t.meetingTitle).slice(0, 1800)}` } }],
    },
  });
}
if (t.notes) {
  children.push({
    object: 'block',
    type: 'paragraph',
    paragraph: {
      rich_text: [{ type: 'text', text: { content: String(t.notes).slice(0, 1900) } }],
    },
  });
}

return [{
  json: {
    parent: { database_id: "TASKS_DB_PLACEHOLDER" },
    properties,
    children,
  },
}];
""".strip().replace("TASKS_DB_PLACEHOLDER", TASKS_DB)

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
            "content": "## Meeting notes → HQ Tasks\n\n1. **Google Drive Trigger** (recommended): polls a flat Gemini-notes folder for new Google Docs.\n2. **Webhook** (optional): Apps Script / manual `{ \"fileId\": \"...\" }`.\n3. OpenRouter (`openrouter/free`) extracts action items.\n4. Creates rows in HQ **Tasks** with Assignee, Origin=Meeting, Drive file ID.\n\nReplace the Drive folder ID before publishing. Connect the four credentials listed in README.md.",
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
                "value": "REPLACE_ME_GEMINI_NOTES_FOLDER_ID",
                "mode": "id",
            },
            "event": "fileCreated",
            "options": {"fileType": "application/vnd.google-apps.document"},
        },
        "credentials": {
            "googleDriveOAuth2Api": {
                "id": "GOOGLE_DRIVE",
                "name": "Google Drive (Save 5 Hours)",
            }
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
        "id": "only-docs",
        "name": "Only Google Docs",
        "type": "n8n-nodes-base.filter",
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
        "position": [740, 320],
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
        "credentials": {
            "googleDriveOAuth2Api": {
                "id": "GOOGLE_DRIVE",
                "name": "Google Drive (Save 5 Hours)",
            }
        },
    },
    {
        "id": "extract",
        "name": "Extract from File",
        "type": "n8n-nodes-base.extractFromFile",
        "typeVersion": 1,
        "position": [980, 320],
        "parameters": {"operation": "text", "options": {}},
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
        "credentials": {
            "notionApi": {
                "id": "NOTION",
                "name": "Notion (Save 5 Hours HQ)",
            }
        },
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
        "credentials": {
            "notionApi": {
                "id": "NOTION",
                "name": "Notion (Save 5 Hours HQ)",
            }
        },
    },
]


def conn(*names: str) -> dict:
    return {
        "main": [[{"node": name, "type": "main", "index": 0} for name in names]]
    }


connections = {
    "Google Drive Trigger": conn("Normalize file"),
    "Webhook": conn("Normalize file"),
    "Normalize file": conn("Only Google Docs"),
    "Only Google Docs": conn("Download Google Doc as text"),
    "Download Google Doc as text": conn("Extract from File"),
    "Extract from File": conn("Build OpenRouter payload"),
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

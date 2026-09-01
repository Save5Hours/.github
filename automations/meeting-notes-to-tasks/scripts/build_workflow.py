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
DRIVE_CONFIRM_PAGE = "3cd0b26fcc4e819bb9ead19d74fb64a6"
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
return $input.all().map((item) => ({ json: buildNotionPage(item.json) }));
""".strip()

ALLOW_DRIVE_CODE = TRANSFORM_JS + "\n\n" + r"""
const info = $input.first().json || {};
const email = info.email || '';
if (!driveCallerAllowed(email)) {
  throw new Error('Drive caller is not on the Save 5 Hours allowlist');
}
const original = $('Extract Google token').first().json;
return [{ json: original }];
""".strip()

PARSE_PUBLIC_CODE = TRANSFORM_JS + "\n\n" + r"""
const parsed = extractPublicDrivePayload($input.first().json || {});
return [{ json: { ...parsed, ok: Boolean(parsed.fileId) } }];
""".strip()

REJECT_PUBLIC_CODE = (
    "throw new Error('Paste a Google Doc URL, or send fileId + text from the bookmarklet');\n"
)

MERGE_PUBLIC_CODE = TRANSFORM_JS + "\n\n" + r"""
function nodeJson(name) {
  try {
    return $(name).first().json || {};
  } catch {
    return {};
  }
}
const fromUrl = nodeJson('Parse Drive URL');
const fromHq = nodeJson('Parse HQ Drive confirmation');
const meta = fromUrl.fileId ? fromUrl : fromHq;
const raw = $input.first().json;
let text = '';
if (typeof raw === 'string') text = raw;
else if (raw && typeof raw === 'object') text = String(raw.data || raw.text || raw.body || '');
if (publicExportLooksLikeHtml(text)) {
  throw new Error('Could not export the Doc. Share it as Anyone with the link can view, or paste the notes text.');
}
if (!noteTextIsReady(text)) {
  throw new Error('Doc is empty or not shared publicly');
}
return [{ json: { ...meta, text, inlineText: text.trim() } }];
""".strip()

PARSE_HQ_CODE = TRANSFORM_JS + "\n\n" + r"""
const page = $('Fetch HQ Drive confirmation').first().json || {};
const blocks = $('Fetch HQ Drive blocks').first().json || {};
const confirmComments = $('Fetch HQ Drive comments').first().json || {};
const query = $('Find HQ Drive URL rows').first().json || {};
let extraComments = [];
try {
  extraComments = $('Fetch HQ Task comments').all().flatMap((item) => {
    const json = item.json || {};
    return json.results || [];
  });
} catch {
  extraComments = [];
}
let extraBlocks = [];
try {
  extraBlocks = $('Fetch HQ Task blocks').all().flatMap((item) => {
    const json = item.json || {};
    return json.results || [];
  });
} catch {
  extraBlocks = [];
}
const extra = {
  blocks: { results: [...(blocks.results || []), ...extraBlocks] },
  comments: { results: [...(confirmComments.results || []), ...extraComments] },
};
const parsed = pickHqDrivePayload(page, extra, query.results || []);
if (!parsed.fileId) {
  return [];
}
return [{ json: parsed }];
""".strip()

EXPAND_HQ_TASKS_CODE = r"""
const query = $input.first().json || {};
const results = Array.isArray(query.results) ? query.results : [];
const fallback = [{ id: '""" + DRIVE_CONFIRM_PAGE + r"""' }];
const pages = results.length ? results : fallback;
return pages.map((row) => ({ json: row }));
""".strip()

SKIP_IMPORTED_HQ_CODE = TRANSFORM_JS + "\n\n" + r"""
const parsed = $('Parse HQ Drive confirmation').first().json;
const query = $input.first().json || {};
const results = Array.isArray(query.results) ? query.results : [];
if (results.length > 0) {
  return [];
}
return [{ json: parsed }];
""".strip()

HQ_FILE_FILTER_BODY = (
    "={{ JSON.stringify({ filter: { property: 'Drive file ID', rich_text: "
    "{ equals: $json.fileId } }, page_size: 1 }) }}"
)

HQ_DRIVE_URL_ROWS_BODY = json.dumps({"page_size": 100})

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
            "content": "## Meeting notes → HQ Tasks\n\nGemini often creates an empty Doc and fills it after the meeting. This workflow watches **file created** and **file updated**, skips notes shorter than 80 characters, then sends text to OpenRouter (`openrouter/free`) and writes HQ Tasks.\n\n**Host n8n 1.123.x** (this repo Dockerfile). n8n 2.x needs extra task runners for Code nodes.\n\n`/webhook/meeting-notes` needs Header Auth (dry-run). `/webhook/meeting-notes-drive` is Apps Script (Google userinfo allowlist). `/webhook/public-drive-doc` accepts a public Doc URL, or `fileId`+`text` from the Drive-setup bookmarklet (private Docs; no sharing change).\n\nEvery minute, **HQ Drive URL poll** reads Drive URL / Drive file ID on every HQ Task, plus that task's comments and the confirmation page body. A public Doc there is exported and written as HQ Tasks (no Google OAuth). Private Docs still need Drive setup paste, Colab, or Apps Script. `fileId`+`text` POSTs continue to OpenRouter in parallel with the HTTP 200 (no public export).",
            "height": 460,
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
        "id": "webhook-drive",
        "name": "Drive Apps Script",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 860],
        "webhookId": "meeting-notes-drive",
        "parameters": {
            "httpMethod": "POST",
            "path": "meeting-notes-drive",
            "responseMode": "onReceived",
            "options": {},
        },
    },
    {
        "id": "extract-google-token",
        "name": "Extract Google token",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [200, 860],
        "parameters": {
            "jsCode": (
                "const src = $input.first().json || {};\n"
                "const body = src.body && typeof src.body === 'object' ? src.body : {};\n"
                "const headers = src.headers || {};\n"
                "const auth = String(headers.authorization || headers.Authorization || '').trim();\n"
                "const payload = Object.keys(body).length ? body : src;\n"
                "let token = String(payload.googleAccessToken || src.googleAccessToken || '').trim();\n"
                "if (!token && /^bearer\\s+/i.test(auth)) {\n"
                "  token = auth.replace(/^bearer\\s+/i, '').trim();\n"
                "}\n"
                "if (!token) {\n"
                "  throw new Error('Missing Google access token');\n"
                "}\n"
                "const nextBody = { ...payload, googleAccessToken: token };\n"
                "return [{ json: { ...src, ...nextBody, googleAccessToken: token, body: nextBody } }];\n"
            ),
        },
    },
    {
        "id": "google-userinfo",
        "name": "Google userinfo",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [400, 860],
        "parameters": {
            "method": "GET",
            "url": "https://www.googleapis.com/oauth2/v2/userinfo",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {
                        "name": "Authorization",
                        "value": "={{ 'Bearer ' + $json.googleAccessToken }}",
                    }
                ]
            },
            "options": {"timeout": 15000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 1000,
    },
    {
        "id": "allow-drive-caller",
        "name": "Allow Drive caller",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [620, 860],
        "parameters": {"jsCode": ALLOW_DRIVE_CODE},
    },
    {
        "id": "webhook-public-doc",
        "name": "Public Drive Doc",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 1100],
        "webhookId": "public-drive-doc",
        "parameters": {
            "httpMethod": "POST",
            "path": "public-drive-doc",
            "responseMode": "responseNode",
            "options": {},
        },
    },
    {
        "id": "webhook-public-doc-get",
        "name": "Public Drive Doc GET",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 1280],
        "webhookId": "public-drive-doc-get",
        "parameters": {
            "httpMethod": "GET",
            "path": "public-drive-doc",
            "responseMode": "responseNode",
            "options": {},
        },
    },
    {
        "id": "webhook-drive-script-get",
        "name": "Drive Apps Script GET",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 1420],
        "webhookId": "meeting-notes-drive-get",
        "parameters": {
            "httpMethod": "GET",
            "path": "meeting-notes-drive",
            "responseMode": "responseNode",
            "options": {},
        },
    },
    {
        "id": "redirect-drive-setup",
        "name": "Redirect to Drive setup",
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": [280, 1340],
        "parameters": {
            "respondWith": "text",
            "responseBody": (
                "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"/>"
                "<meta http-equiv=\"refresh\" content=\"0;url=/webhook/drive-setup\"/>"
                "<title>Drive setup</title>"
                "<body style=\"font:16px/1.45 system-ui;padding:2rem\">"
                "<p>This webhook is POST-only. Opening it in the browser does not send a Doc.</p>"
                "<p><a href=\"/webhook/drive-setup\">Open the Drive setup form</a> "
                "(paste the Gemini Doc URL + notes, or use the bookmarklet on docs.google.com).</p>"
                "</body></html>"
            ),
            "options": {
                "responseCode": 200,
                "responseHeaders": {
                    "entries": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                },
            },
        },
    },
    {
        "id": "parse-drive-url",
        "name": "Parse Drive URL",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [220, 1100],
        "parameters": {"jsCode": PARSE_PUBLIC_CODE},
    },
    {
        "id": "has-drive-file-id",
        "name": "Has Drive file ID",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [400, 1100],
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
                        "id": "drive-file-id-ok",
                        "leftValue": "={{ $json.fileId }}",
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
        "id": "respond-public-doc",
        "name": "Respond public Doc",
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": [620, 980],
        "parameters": {
            "respondWith": "text",
            "responseBody": (
                "={{ '<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"/>"
                "<title>Sent to n8n</title><body style=\"font:16px/1.45 system-ui;padding:2rem\">"
                "<p>Received. OpenRouter will create HQ Tasks with this Drive file ID in about 30 seconds.</p>"
                "<p>Drive file ID: <code>' + $json.fileId + '</code></p>"
                "<p><a href=\"https://app.notion.com/p/3cd0b26fcc4e819bb9ead19d74fb64a6\">"
                "Confirm the Drive folder</a> · "
                "<a href=\"/webhook/drive-setup\">Back to Drive setup</a></p></body></html>' }}"
            ),
            "options": {
                "responseCode": 200,
                "responseHeaders": {
                    "entries": [
                        {"name": "Content-Type", "value": "text/html; charset=utf-8"}
                    ]
                },
            },
        },
    },
    {
        "id": "respond-public-doc-error",
        "name": "Respond public Doc error",
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": [620, 1240],
        "parameters": {
            "respondWith": "text",
            "responseBody": (
                "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"/>"
                "<title>Missing Google Doc</title>"
                "<body style=\"font:16px/1.45 system-ui;padding:2rem\">"
                "<p>Paste a Google Doc URL, and the notes text if the Doc is private.</p>"
                "<p>Go back to <a href=\"/webhook/drive-setup\">Drive setup</a>, "
                "or drag <strong>Send this Doc to HQ Tasks</strong> onto a "
                "<code>docs.google.com</code> tab.</p></body></html>"
            ),
            "options": {
                "responseCode": 400,
                "responseHeaders": {
                    "entries": [
                        {"name": "Content-Type", "value": "text/html; charset=utf-8"}
                    ]
                },
            },
        },
    },
    {
        "id": "reject-missing-drive-url",
        "name": "Reject missing Drive URL",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [860, 1240],
        "parameters": {"jsCode": REJECT_PUBLIC_CODE},
    },
    {
        "id": "has-doc-text",
        "name": "Has Doc text already",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [860, 980],
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
                        "id": "doc-text-ok",
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
        "id": "export-public-doc",
        "name": "Export public Doc",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1080, 1120],
        "parameters": {
            "method": "GET",
            "url": "={{ $json.exportUrl }}",
            "options": {
                "timeout": 45000,
                "response": {"response": {"fullResponse": False, "responseFormat": "text"}},
            },
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 1000,
    },
    {
        "id": "merge-public-doc",
        "name": "Merge public Doc",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1300, 1120],
        "parameters": {"jsCode": MERGE_PUBLIC_CODE},
    },
    {
        "id": "hq-drive-url-poll",
        "name": "HQ Drive URL poll",
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [0, 1480],
        "parameters": {
            "rule": {
                "interval": [{"field": "minutes", "minutesInterval": 1}]
            }
        },
    },
    {
        "id": "fetch-hq-drive-confirmation",
        "name": "Fetch HQ Drive confirmation",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [220, 1480],
        "parameters": {
            "method": "GET",
            "url": f"https://api.notion.com/v1/pages/{DRIVE_CONFIRM_PAGE}",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "options": {"timeout": 30000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "fetch-hq-drive-blocks",
        "name": "Fetch HQ Drive blocks",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [340, 1480],
        "parameters": {
            "method": "GET",
            "url": f"https://api.notion.com/v1/blocks/{DRIVE_CONFIRM_PAGE}/children?page_size=100",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "options": {"timeout": 30000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "fetch-hq-drive-comments",
        "name": "Fetch HQ Drive comments",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [460, 1480],
        "parameters": {
            "method": "GET",
            "url": f"https://api.notion.com/v1/comments?block_id={DRIVE_CONFIRM_PAGE}",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "options": {"timeout": 30000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "find-hq-drive-url-rows",
        "name": "Find HQ Drive URL rows",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [520, 1480],
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
            "jsonBody": HQ_DRIVE_URL_ROWS_BODY,
            "options": {"timeout": 30000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "expand-hq-tasks",
        "name": "Expand HQ Tasks",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [540, 1480],
        "parameters": {
            "mode": "runOnceForAllItems",
            "jsCode": EXPAND_HQ_TASKS_CODE,
        },
    },
    {
        "id": "fetch-hq-task-comments",
        "name": "Fetch HQ Task comments",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [560, 1480],
        "alwaysOutputData": True,
        "parameters": {
            "method": "GET",
            "url": "={{ 'https://api.notion.com/v1/comments?block_id=' + $json.id }}",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "options": {"timeout": 30000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "fetch-hq-task-blocks",
        "name": "Fetch HQ Task blocks",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [600, 1480],
        "alwaysOutputData": True,
        "parameters": {
            "method": "GET",
            "url": "={{ 'https://api.notion.com/v1/blocks/' + $('Expand HQ Tasks').item.json.id + '/children?page_size=100' }}",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "notionApi",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Notion-Version", "value": "2022-06-28"},
                ]
            },
            "options": {"timeout": 30000},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "parse-hq-drive-confirmation",
        "name": "Parse HQ Drive confirmation",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [640, 1480],
        "parameters": {
            "mode": "runOnceForAllItems",
            "jsCode": PARSE_HQ_CODE,
        },
    },
    {
        "id": "find-hq-drive-duplicates",
        "name": "Find HQ Drive duplicates",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [700, 1480],
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
            "jsonBody": HQ_FILE_FILTER_BODY,
            "options": {},
        },
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 2000,
        "credentials": NOTION_CREDS,
    },
    {
        "id": "skip-imported-hq-drive",
        "name": "Skip imported HQ Drive",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [940, 1480],
        "parameters": {"jsCode": SKIP_IMPORTED_HQ_CODE},
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
    "Drive Apps Script": conn("Extract Google token"),
    "Extract Google token": conn("Google userinfo"),
    "Google userinfo": conn("Allow Drive caller"),
    "Allow Drive caller": conn("Normalize file"),
    "Public Drive Doc": conn("Parse Drive URL"),
    "Public Drive Doc GET": conn("Redirect to Drive setup"),
    "Drive Apps Script GET": conn("Redirect to Drive setup"),
    "Parse Drive URL": conn("Has Drive file ID"),
    "Has Drive file ID": {
        "main": [
            [
                {"node": "Respond public Doc", "type": "main", "index": 0},
                {"node": "Has Doc text already", "type": "main", "index": 0},
            ],
            [{"node": "Respond public Doc error", "type": "main", "index": 0}],
        ]
    },
    "Respond public Doc error": conn("Reject missing Drive URL"),
    "Has Doc text already": {
        "main": [
            [{"node": "Normalize file", "type": "main", "index": 0}],
            [{"node": "Export public Doc", "type": "main", "index": 0}],
        ]
    },
    "Export public Doc": conn("Merge public Doc"),
    "Merge public Doc": conn("Normalize file"),
    "HQ Drive URL poll": conn("Fetch HQ Drive confirmation"),
    "Fetch HQ Drive confirmation": conn("Fetch HQ Drive blocks"),
    "Fetch HQ Drive blocks": conn("Fetch HQ Drive comments"),
    "Fetch HQ Drive comments": conn("Find HQ Drive URL rows"),
    "Find HQ Drive URL rows": conn("Expand HQ Tasks"),
    "Expand HQ Tasks": conn("Fetch HQ Task comments"),
    "Fetch HQ Task comments": conn("Fetch HQ Task blocks"),
    "Fetch HQ Task blocks": conn("Parse HQ Drive confirmation"),
    "Parse HQ Drive confirmation": conn("Find HQ Drive duplicates"),
    "Find HQ Drive duplicates": conn("Skip imported HQ Drive"),
    "Skip imported HQ Drive": conn("Has Doc text already"),
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

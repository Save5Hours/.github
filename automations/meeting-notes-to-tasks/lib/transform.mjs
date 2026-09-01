export const TASKS_DATABASE_ID = '3bc0b26fcc4e8057b7ade1cdf5a67e6e';
export const MIN_NOTE_CHARS = 80;

export const PEOPLE = {
  antoine: '3bcd872b-594c-8157-a68b-0002ec224796',
  martin: '3bcd872b-594c-81b9-acfe-0002ebe41550',
  roman: '3bcd872b-594c-81a9-bf7d-00029eb21064',
};

export const ALIASES = {
  antoine: 'antoine',
  'antoine bejarano': 'antoine',
  'antoine bejarano alvarez': 'antoine',
  'antoine@save5hours.ch': 'antoine',
  martin: 'martin',
  'martin@save5hours.ch': 'martin',
  roman: 'roman',
  ronald: 'roman',
  'roman cajka': 'roman',
  'roman@save5hours.ch': 'roman',
  'roman.cajka@gmail.com': 'roman',
};

/** Google accounts allowed to POST /webhook/meeting-notes-drive (Apps Script). */
export const DRIVE_CALLER_EXACT = [
  'antoine@save5hours.ch',
  'martin@save5hours.ch',
  'roman@save5hours.ch',
  'deevlylabs@gmail.com',
  'antubejar96@gmail.com',
  'roman.cajka@gmail.com',
];

export function driveCallerAllowed(email) {
  const value = String(email || '').trim().toLowerCase();
  if (!value.includes('@')) return false;
  if (DRIVE_CALLER_EXACT.includes(value)) return true;
  return value.endsWith('@save5hours.ch');
}

export function parseDriveFileId(text) {
  const raw = String(text || '');
  const doc = raw.match(/docs\.google\.com\/document\/(?:u\/\d+\/)?d\/([a-zA-Z0-9_-]{10,})/i)
    || raw.match(/drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]{10,})/i)
    || raw.match(/drive\.google\.com\/open\?id=([a-zA-Z0-9_-]{10,})/i)
    || raw.match(/FILE_ID\s+([a-zA-Z0-9_-]{10,})/i);
  const fromUrl = Boolean(doc);
  const candidate = doc ? doc[1] : raw.trim();
  if (!candidate || candidate.toLowerCase().startsWith('inline-')) return '';
  if (candidate.toUpperCase() === 'REPLACE_ME_GEMINI_NOTES_FOLDER_ID') return '';
  const blocked = new Set([
    'apps-script-source',
    'drive-setup',
    'meeting-notes',
    'public-drive-doc',
    'meeting-notes-drive',
  ]);
  if (blocked.has(candidate.toLowerCase())) return '';
  if (fromUrl) {
    if (!/^[a-zA-Z0-9_-]{10,}$/.test(candidate)) return '';
    return candidate;
  }
  if (!/^[0-9][a-zA-Z0-9_-]{19,}$/.test(candidate)) return '';
  return candidate;
}

export function firstScalar(value) {
  if (Array.isArray(value)) return firstScalar(value[0]);
  if (value == null) return '';
  if (typeof value === 'object') return '';
  return String(value).trim();
}

/** Flatten an n8n webhook item (JSON or form POST) into a Drive Doc payload. */
export function extractPublicDrivePayload(src) {
  const root = src && typeof src === 'object' ? src : {};
  let body = {};
  if (root.body && typeof root.body === 'object' && !Array.isArray(root.body)) {
    body = root.body;
  } else if (typeof root.body === 'string' && root.body.trim().startsWith('{')) {
    try {
      const parsed = JSON.parse(root.body);
      if (parsed && typeof parsed === 'object') body = parsed;
    } catch {
      body = {};
    }
  }
  const query = root.query && typeof root.query === 'object' ? root.query : {};
  const layers = [body, query, root];
  const pick = (...keys) => {
    for (const layer of layers) {
      for (const key of keys) {
        const value = firstScalar(layer[key]);
        if (value) return value;
      }
    }
    return '';
  };
  const url = pick('url', 'driveUrl', 'docUrl');
  const text = pick('text', 'notes', 'inlineText');
  let extra = '';
  if (typeof root.body === 'string') extra = root.body;
  else if (typeof body.body === 'string') extra = body.body;
  const fileId = parseDriveFileId(`${pick('fileId', 'id')}\n${url}\n${text}\n${extra}`);
  const ready = noteTextIsReady(text);
  const name = pick('name', 'title') || 'Gemini notes';
  return {
    fileId,
    name,
    mimeType: 'application/vnd.google-apps.document',
    webViewLink: fileId ? `https://docs.google.com/document/d/${fileId}/edit` : '',
    exportUrl: fileId ? `https://docs.google.com/document/d/${fileId}/export?format=txt` : '',
    text: ready ? text : '',
    inlineText: ready ? text : '',
    hasText: ready,
  };
}

export function notionPlain(prop) {
  if (!prop || typeof prop !== 'object') return '';
  if (typeof prop.url === 'string' && prop.url.trim()) return prop.url.trim();
  const spans = prop.rich_text || prop.title || [];
  if (!Array.isArray(spans)) return '';
  return spans.map((span) => span.plain_text || span.text?.content || '').join('').trim();
}

export function notionBlockText(blocks) {
  const results = (blocks && blocks.results) || (Array.isArray(blocks) ? blocks : []);
  const parts = [];
  for (const block of results) {
    if (!block || typeof block !== 'object') continue;
    const inner = block[block.type] || {};
    const spans = inner.rich_text || inner.caption || [];
    if (Array.isArray(spans)) {
      for (const span of spans) {
        parts.push(span.plain_text || '');
        if (span.href) parts.push(span.href);
      }
    }
    if (typeof inner.url === 'string') parts.push(inner.url);
  }
  return parts.filter(Boolean).join('\n');
}

/** Notion comments list (GET /v1/comments?block_id=) → concatenated text. */
export function notionCommentsText(comments) {
  return notionCommentChunks(comments).join('\n');
}

function spanText(spans) {
  if (!Array.isArray(spans)) return '';
  const parts = [];
  for (const span of spans) {
    parts.push(span.plain_text || '');
    if (span.href) parts.push(span.href);
  }
  return parts.filter(Boolean).join('\n');
}

function notionBlockChunks(blocks) {
  const results = (blocks && blocks.results) || (Array.isArray(blocks) ? blocks : []);
  const chunks = [];
  for (const block of results) {
    if (!block || typeof block !== 'object') continue;
    const inner = block[block.type] || {};
    const text = [spanText(inner.rich_text || inner.caption), inner.url].filter(Boolean).join('\n');
    if (text.trim()) chunks.push(text);
  }
  return chunks;
}

function notionCommentChunks(comments) {
  const results = (comments && comments.results) || (Array.isArray(comments) ? comments : []);
  const chunks = [];
  for (const row of results) {
    if (!row || typeof row !== 'object') continue;
    const text = spanText(row.rich_text);
    if (text.trim()) chunks.push(text);
  }
  return chunks;
}

const HQ_INSTRUCTION_MARKERS = [
  'webhook_secret',
  'verifydrivepath',
  'send this doc to hq tasks',
  'n8n is already active',
  'ignore earlier comments',
  'ignore older comments',
  'paste the drive folder',
  'you do not need an n8n login',
  'copy apps script',
  'meeting notes webhook secret',
  'do not paste secrets',
  'drag this link to your bookmarks',
];

function looksLikeHqInstruction(text) {
  const lower = String(text || '').toLowerCase();
  return HQ_INSTRUCTION_MARKERS.some((marker) => lower.includes(marker));
}

function stripDriveUrls(text) {
  return String(text || '')
    .replace(/https?:\/\/(?:docs|drive)\.google\.com\S+/gi, ' ')
    .replace(/FILE_ID\s+[a-zA-Z0-9_-]{10,}/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Notes a human pasted on the HQ confirmation task (not the runbook body). */
export function hqPastedNotes(extra) {
  let chunks = [];
  if (typeof extra === 'string') {
    chunks = [extra];
  } else if (extra && typeof extra === 'object') {
    chunks = [
      ...notionBlockChunks(extra.blocks || extra),
      ...notionCommentChunks(extra.comments || extra),
    ];
  }
  const notes = [];
  for (const chunk of chunks) {
    if (looksLikeHqInstruction(chunk)) continue;
    const stripped = stripDriveUrls(chunk);
    if (noteTextIsReady(stripped)) notes.push(stripped);
  }
  return notes.join('\n\n');
}

/** Notion HQ confirmation page → Drive Doc payload (no inline-* ids). */
export function parseHqDriveConfirmation(page, extra) {
  const props = page && page.properties && typeof page.properties === 'object'
    ? page.properties
    : {};
  let extraText = '';
  if (typeof extra === 'string') {
    extraText = extra;
  } else if (extra && typeof extra === 'object') {
    extraText = [
      notionBlockText(extra.blocks || extra),
      notionCommentsText(extra.comments || extra),
    ].filter(Boolean).join('\n');
  }
  return extractPublicDrivePayload({
    url: `${notionPlain(props['Drive URL'])}\n${extraText}`,
    fileId: notionPlain(props['Drive file ID']),
    text: hqPastedNotes(extra),
    name: notionPlain(props.Name) || 'Gemini notes',
  });
}

export function noteTextIsReady(text) {
  return String(text || '').replace(/\s+/g, ' ').trim().length >= MIN_NOTE_CHARS;
}

/** True when a public export URL returned login/error HTML instead of notes. */
export function publicExportLooksLikeHtml(text) {
  const lower = String(text || '').toLowerCase();
  return (
    lower.includes('<html')
    || lower.includes('<!doctype html')
    || lower.includes('accounts.google')
  );
}

function inlineFileId(text) {
  let hash = 0;
  const raw = String(text || '');
  for (let i = 0; i < raw.length; i += 1) {
    hash = (Math.imul(31, hash) + raw.charCodeAt(i)) | 0;
  }
  return `inline-${(hash >>> 0).toString(16)}`;
}

export function normalizeMeetingInput(item) {
  const src = item && typeof item === 'object' ? item : {};
  const body = src.body && typeof src.body === 'object' ? src.body : {};
  const inlineText = String(
    src.text || src.notes || src.inlineText || body.text || body.notes || '',
  ).trim();
  const fileId = String(src.id || src.fileId || body.id || body.fileId || '').trim()
    || (inlineText ? inlineFileId(inlineText) : '');
  if (!fileId) {
    throw new Error(
      'Missing Google Drive fileId or notes text. Drive Trigger should send file.id; webhook body must be { "fileId": "..." } or { "text": "..." }.',
    );
  }
  const mimeType = src.mimeType || body.mimeType
    || (inlineText ? 'text/plain' : 'application/vnd.google-apps.document');
  const name = src.name || body.name || 'Untitled meeting notes';
  const webViewLink = src.webViewLink || body.webViewLink
    || (String(fileId).startsWith('inline-')
      ? ''
      : `https://drive.google.com/file/d/${fileId}/view`);
  return {
    fileId,
    name,
    mimeType,
    webViewLink,
    inlineText,
  };
}

export function extractJson(text) {
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

export function mapAssignee(value) {
  const key = String(value || '').trim().toLowerCase();
  const mapped = ALIASES[key] || (PEOPLE[key] ? key : 'antoine');
  return { key: mapped, id: PEOPLE[mapped] };
}

export function mapPriority(value) {
  const p = String(value || 'Medium');
  if (p === 'High' || p === 'Low' || p === 'Medium') return p;
  const lower = p.toLowerCase();
  if (lower.includes('high') || lower.includes('urgent')) return 'High';
  if (lower.includes('low')) return 'Low';
  return 'Medium';
}

export function parseOpenRouterContent(content, meta) {
  const parsed = extractJson(content);
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

  return {
    meetingTitle: parsed.meeting_title || meta.fileName,
    driveFileId: meta.fileId,
    driveUrl: meta.webViewLink,
    taskCount: tasks.length,
    tasks,
  };
}

export function skipDuplicateTasks(parsed, notionQuery) {
  const results = Array.isArray(notionQuery && notionQuery.results) ? notionQuery.results : [];
  const existingTitles = new Set(
    results.map((page) => {
      const title = page.properties && page.properties.Name && page.properties.Name.title
        && page.properties.Name.title[0]
        ? page.properties.Name.title[0].plain_text
        : '';
      return title.trim().toLowerCase();
    }).filter(Boolean),
  );

  const tasks = (parsed.tasks || []).filter((task) => {
    return !existingTitles.has(String(task.title).trim().toLowerCase());
  });

  return {
    ...parsed,
    existingCount: existingTitles.size,
    skipped: (parsed.tasks || []).length - tasks.length,
    taskCount: tasks.length,
    tasks,
  };
}

export function buildNotionPage(task) {
  const title = String(task.title || 'Untitled task').slice(0, 2000);
  const properties = {
    Name: { title: [{ text: { content: title } }] },
    Assignee: { people: task.assigneeId ? [{ id: task.assigneeId }] : [] },
    Status: { status: { name: 'Not started' } },
    Priority: { select: { name: task.priority || 'Medium' } },
    Origin: { select: { name: 'Meeting' } },
    'Drive file ID': { rich_text: [{ text: { content: task.driveFileId || '' } }] },
    'Drive URL': { url: task.driveUrl || null },
  };

  if (task.due) {
    properties['Due date'] = { date: { start: task.due } };
  }

  const children = [];
  if (task.meetingTitle) {
    children.push({
      object: 'block',
      type: 'paragraph',
      paragraph: {
        rich_text: [{ type: 'text', text: { content: `From meeting: ${String(task.meetingTitle).slice(0, 1800)}` } }],
      },
    });
  }
  if (task.notes) {
    children.push({
      object: 'block',
      type: 'paragraph',
      paragraph: {
        rich_text: [{ type: 'text', text: { content: String(task.notes).slice(0, 1900) } }],
      },
    });
  }

  return {
    parent: { database_id: TASKS_DATABASE_ID },
    properties,
    children,
  };
}

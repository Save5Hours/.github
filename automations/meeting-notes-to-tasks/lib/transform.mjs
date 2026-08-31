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
  const doc = raw.match(/docs\.google\.com\/document\/d\/([a-zA-Z0-9_-]{10,})/i)
    || raw.match(/drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]{10,})/i)
    || raw.match(/FILE_ID\s+([a-zA-Z0-9_-]{10,})/i);
  const candidate = doc ? doc[1] : raw.trim();
  if (!candidate || candidate.toLowerCase().startsWith('inline-')) return '';
  if (!/^[a-zA-Z0-9_-]{10,}$/.test(candidate)) return '';
  if (candidate.toUpperCase() === 'REPLACE_ME_GEMINI_NOTES_FOLDER_ID') return '';
  return candidate;
}

export function noteTextIsReady(text) {
  return String(text || '').replace(/\s+/g, ' ').trim().length >= MIN_NOTE_CHARS;
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

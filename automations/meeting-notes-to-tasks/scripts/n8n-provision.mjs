#!/usr/bin/env node
/**
 * Boot-time setup for the Save 5 Hours n8n volume:
 * - optional license:clear (N8N_CLEAR_LICENSE=true, one boot only)
 * - import / patch the meeting-notes workflow
 * - import OpenRouter / Notion / webhook / Google OAuth creds from Railway env
 *
 * Never logs secret values. Does not set N8N_LICENSE_ACTIVATION_KEY.
 */
import { spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

const PLACEHOLDER = 'REPLACE_ME_GEMINI_NOTES_FOLDER_ID';
const WF_NAME = 'Meeting notes → HQ Tasks';
const WF_ID = 'KfrQb6c79aJPPxYE';
const SRC = process.env.SAVE5HOURS_WF_SRC || '/opt/save5hours/meeting-notes-to-tasks.json';
const USER_FOLDER = process.env.N8N_USER_FOLDER || '/home/node/.n8n';
const OUT_DIR = '/tmp/save5hours-n8n-provision';
const DB_PATH = `${USER_FOLDER}/database.sqlite`;

function envPresent(name) {
  return Boolean(process.env[name] && String(process.env[name]).trim());
}

function envValue(name) {
  return String(process.env[name] || '').trim();
}

function run(args) {
  const shown = args.map((a) => (String(a).includes('KEY') ? '[redacted]' : a));
  console.log('save5hours:', shown.join(' '));
  const result = spawnSync(args[0], args.slice(1), {
    encoding: 'utf8',
    env: {
      ...process.env,
      HOME: '/home/node',
      N8N_USER_FOLDER: USER_FOLDER,
    },
  });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  return result.status === 0;
}

function openDb(readonly = false) {
  if (!existsSync(DB_PATH)) return null;
  return new DatabaseSync(DB_PATH, readonly ? { readOnly: true } : {});
}

function ownerIds(db) {
  if (!db) return { userId: '', projectId: '' };
  try {
    const user = db.prepare('SELECT id FROM user LIMIT 1').get();
    const project = db.prepare("SELECT id FROM project WHERE type = 'personal' LIMIT 1").get();
    return {
      userId: user?.id || '',
      projectId: project?.id || '',
    };
  } catch {
    return { userId: '', projectId: '' };
  }
}

console.log(
  'save5hours: provision',
  `uid=${process.getuid?.() ?? 'unknown'}`,
  `home=${process.env.HOME || ''}`,
  `userFolder=${USER_FOLDER}`,
);

mkdirSync(OUT_DIR, { recursive: true });
mkdirSync(USER_FOLDER, { recursive: true });

if (process.env.N8N_CLEAR_LICENSE === 'true') {
  console.log('save5hours: clearing local n8n license cert on this volume');
  run(['n8n', 'license:clear']);
}

const folder = envValue('GEMINI_NOTES_FOLDER_ID');
const workflow = JSON.parse(readFileSync(SRC, 'utf8'));
workflow.id = WF_ID;
workflow.name = WF_NAME;
workflow.active = false;
for (const node of workflow.nodes) {
  if (node.type !== 'n8n-nodes-base.googleDriveTrigger') continue;
  if (folder && folder !== PLACEHOLDER) {
    if (node.parameters?.folderToWatch) {
      node.parameters.folderToWatch.value = folder;
    }
    node.disabled = false;
  } else {
    node.disabled = true;
  }
}

const runtimeWf = `${OUT_DIR}/workflow.json`;
writeFileSync(runtimeWf, `${JSON.stringify(workflow, null, 2)}\n`);

let db = openDb(false);
let { userId, projectId } = ownerIds(db);

function closeDb() {
  try {
    db?.close?.();
  } catch {
    // already closed
  }
  db = null;
}

function reopenDb() {
  closeDb();
  db = openDb(false);
  ({ userId, projectId } = ownerIds(db));
  return db;
}

function importWorkflow() {
  const args = ['n8n', 'import:workflow', '--input', runtimeWf];
  if (projectId) args.push('--projectId', projectId);
  else if (userId) args.push('--userId', userId);
  return run(args);
}

function existingWorkflow(database) {
  if (!database) return null;
  try {
    return database.prepare(
      'SELECT id FROM workflow_entity WHERE id = ? OR name = ? LIMIT 1',
    ).get(WF_ID, WF_NAME);
  } catch {
    return null;
  }
}

const hashed = createHash('sha256').update(JSON.stringify({
  nodes: workflow.nodes,
  connections: workflow.connections,
  folder: folder || PLACEHOLDER,
})).digest('hex');
const wfMarker = `${USER_FOLDER}/.save5hours-wf-${hashed}`;

if (!existingWorkflow(db)) {
  closeDb();
  if (importWorkflow()) {
    writeFileSync(wfMarker, '');
  } else {
    console.error('save5hours: workflow import deferred until next boot');
  }
  reopenDb();
}

const live = existingWorkflow(db);
if (live && db) {
  try {
    db.prepare(
      `UPDATE workflow_entity
       SET nodes = ?, connections = ?, versionId = ?, updatedAt = datetime('now')
       WHERE id = ?`,
    ).run(
      JSON.stringify(workflow.nodes),
      JSON.stringify(workflow.connections),
      randomUUID(),
      live.id,
    );
    writeFileSync(wfMarker, '');
    console.log(
      folder && folder !== PLACEHOLDER
        ? 'save5hours: patched workflow Drive folder from GEMINI_NOTES_FOLDER_ID'
        : 'save5hours: Drive triggers disabled until GEMINI_NOTES_FOLDER_ID is set',
    );
  } catch (error) {
    console.error('save5hours: workflow patch failed', error.message);
  }
}

const creds = [];
if (envPresent('OPENROUTER_API_KEY')) {
  const key = envValue('OPENROUTER_API_KEY');
  creds.push({
    id: 'OPENROUTER',
    name: 'OpenRouter',
    type: 'httpHeaderAuth',
    data: {
      name: 'Authorization',
      value: key.startsWith('Bearer ') ? key : `Bearer ${key}`,
    },
  });
}
if (envPresent('NOTION_API_KEY')) {
  creds.push({
    id: 'NOTION',
    name: 'Notion (Save 5 Hours HQ)',
    type: 'notionApi',
    data: { apiKey: envValue('NOTION_API_KEY') },
  });
}
if (envPresent('N8N_WEBHOOK_SECRET')) {
  creds.push({
    id: 'WEBHOOK_SECRET',
    name: 'Meeting notes webhook secret',
    type: 'httpHeaderAuth',
    data: {
      name: 'X-Webhook-Secret',
      value: envValue('N8N_WEBHOOK_SECRET'),
    },
  });
}
if (envPresent('GOOGLE_OAUTH_CLIENT_ID') && envPresent('GOOGLE_OAUTH_CLIENT_SECRET')) {
  creds.push({
    id: 'GOOGLE_DRIVE',
    name: 'Google Drive (Save 5 Hours)',
    type: 'googleDriveOAuth2Api',
    data: {
      clientId: envValue('GOOGLE_OAUTH_CLIENT_ID'),
      clientSecret: envValue('GOOGLE_OAUTH_CLIENT_SECRET'),
    },
  });
}

if (creds.length) {
  if (db) {
    for (const cred of creds) {
      try {
        db.prepare('DELETE FROM shared_credentials WHERE credentialsId = ?').run(cred.id);
        db.prepare('DELETE FROM credentials_entity WHERE id = ? OR (name = ? AND type = ?)').run(
          cred.id,
          cred.name,
          cred.type,
        );
      } catch (error) {
        console.error('save5hours: could not replace credential', cred.name, error.message);
      }
    }
  }
  const credFile = `${OUT_DIR}/credentials.json`;
  writeFileSync(credFile, `${JSON.stringify(creds, null, 2)}\n`);
  closeDb();
  const args = [
    'n8n',
    'import:credentials',
    '--input',
    credFile,
  ];
  if (projectId) args.push('--projectId', projectId);
  else if (userId) args.push('--userId', userId);
  console.log(`save5hours: importing credentials (${creds.map((c) => c.name).join(', ')})`);
  if (!run(args)) {
    console.error('save5hours: credential import failed; paste them in the n8n Credentials UI');
  }
  reopenDb();
  if (db && projectId) {
    for (const cred of creds) {
      try {
        db.prepare(
          `INSERT OR IGNORE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
           VALUES (?, ?, 'credential:owner', datetime('now'), datetime('now'))`,
        ).run(cred.id, projectId);
      } catch {
        // import:credentials already shared them
      }
    }
  }
}

closeDb();

const canActivate = envPresent('OPENROUTER_API_KEY') && envPresent('NOTION_API_KEY')
  && process.env.N8N_ACTIVATE_WORKFLOW === 'true';
if (canActivate) {
  console.log('save5hours: activating workflow');
  run(['n8n', 'update:workflow', '--id', WF_ID, '--active', 'true']);
}

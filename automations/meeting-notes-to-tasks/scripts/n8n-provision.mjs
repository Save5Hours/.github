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
import { createCipheriv, createHash, randomBytes, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const PLACEHOLDER = 'REPLACE_ME_GEMINI_NOTES_FOLDER_ID';
const WF_NAME = 'Meeting notes → HQ Tasks';
const WF_ID = 'KfrQb6c79aJPPxYE';
const SRC = process.env.SAVE5HOURS_WF_SRC || '/opt/save5hours/meeting-notes-to-tasks.json';
const BASE_FOLDER = process.env.N8N_USER_FOLDER || '/home/node/.n8n';

function resolveLiveDbPath(baseFolder) {
  const candidates = [`${baseFolder}/.n8n/database.sqlite`, `${baseFolder}/database.sqlite`];
  let fallback = candidates.find((path) => existsSync(path)) || candidates[1];
  let best = fallback;
  let bestActive = -1;
  for (const path of candidates) {
    if (!existsSync(path)) continue;
    try {
      const db = new DatabaseSync(path, { readOnly: true });
      const row = db.prepare(
        'SELECT COUNT(*) AS n FROM workflow_entity WHERE active = 1',
      ).get();
      db.close();
      const active = Number(row?.n || 0);
      if (active > bestActive) {
        bestActive = active;
        best = path;
      }
    } catch {
      // unreadable copy
    }
  }
  return best;
}

const DB_PATH = resolveLiveDbPath(BASE_FOLDER);
const USER_FOLDER = dirname(DB_PATH);
const OUT_DIR = '/tmp/save5hours-n8n-provision';

function encryptionKey() {
  if (process.env.N8N_ENCRYPTION_KEY && process.env.N8N_ENCRYPTION_KEY.trim()) {
    return process.env.N8N_ENCRYPTION_KEY.trim();
  }
  const configPath = `${USER_FOLDER}/config`;
  if (existsSync(configPath)) {
    const cfg = JSON.parse(readFileSync(configPath, 'utf8'));
    if (cfg.encryptionKey) return String(cfg.encryptionKey);
  }
  throw new Error('N8N_ENCRYPTION_KEY missing');
}

function encryptCredentialData(data) {
  const salt = randomBytes(8);
  const password = Buffer.concat([Buffer.from(encryptionKey(), 'binary'), salt]);
  const hash1 = createHash('md5').update(password).digest();
  const hash2 = createHash('md5').update(Buffer.concat([hash1, password])).digest();
  const iv = createHash('md5').update(Buffer.concat([hash2, password])).digest();
  const key = Buffer.concat([hash1, hash2]);
  const cipher = createCipheriv('aes-256-cbc', key, iv);
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(data), 'utf8'), cipher.final()]);
  const header = Buffer.from('53616c7465645f5f', 'hex');
  return Buffer.concat([header, salt, encrypted]).toString('base64');
}

function credentialIdsFromWorkflow(database, workflowId) {
  if (!database || !workflowId) return {};
  try {
    const row = database.prepare('SELECT nodes FROM workflow_entity WHERE id = ?').get(workflowId);
    const nodes = JSON.parse(row?.nodes || '[]');
    const ids = {};
    for (const node of nodes) {
      for (const spec of Object.values(node.credentials || {})) {
        const name = String(spec?.name || '');
        if (name && spec.id) ids[name] = spec.id;
      }
    }
    return ids;
  } catch {
    return {};
  }
}

function retargetWorkflowCreds(nodes, idByName) {
  for (const node of nodes) {
    for (const spec of Object.values(node.credentials || {})) {
      const liveId = idByName[String(spec?.name || '')];
      if (liveId) spec.id = liveId;
    }
  }
  return nodes;
}

function upsertCredentials(database, credsList, project, preferredIds = {}) {
  if (!database || !credsList.length) return;
  const now = new Date().toISOString().replace('T', ' ').replace('Z', '');
  for (const cred of credsList) {
    const named = database.prepare(
      'SELECT id FROM credentials_entity WHERE name = ? AND type = ? LIMIT 1',
    ).get(cred.name, cred.type);
    const keepId = preferredIds[cred.name] || named?.id || cred.id;
    const encrypted = encryptCredentialData(cred.data);
    const row = database.prepare('SELECT id FROM credentials_entity WHERE id = ?').get(keepId);
    if (row) {
      database.prepare(
        'UPDATE credentials_entity SET data = ?, updatedAt = ? WHERE id = ?',
      ).run(encrypted, now, keepId);
      continue;
    }
    database.prepare(
      `INSERT INTO credentials_entity
        (id, name, data, type, createdAt, updatedAt, isManaged, isGlobal)
       VALUES (?, ?, ?, ?, ?, ?, 0, 0)`,
    ).run(keepId, cred.name, encrypted, cred.type, now, now);
    if (project) {
      database.prepare(
        `INSERT OR IGNORE INTO shared_credentials
          (credentialsId, projectId, role, createdAt, updatedAt)
         VALUES (?, ?, 'credential:owner', ?, ?)`,
      ).run(keepId, project, now, now);
    }
  }
  try {
    database.prepare('PRAGMA wal_checkpoint(TRUNCATE)').run();
  } catch {
    // ignore
  }
}

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
      // CLI import still uses the volume root. Direct sqlite writes use USER_FOLDER
      // (this host stores the live DB at /home/node/.n8n/.n8n).
      N8N_USER_FOLDER: BASE_FOLDER,
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
  `db=${DB_PATH}`,
);

mkdirSync(OUT_DIR, { recursive: true });
mkdirSync(USER_FOLDER, { recursive: true });

if (process.env.N8N_CLEAR_LICENSE === 'true') {
  console.log('save5hours: clearing local n8n license cert on this volume');
  run(['n8n', 'license:clear']);
}

const folder = envValue('GEMINI_NOTES_FOLDER_ID');
const googleReady = envPresent('GOOGLE_OAUTH_CLIENT_ID') && envPresent('GOOGLE_OAUTH_CLIENT_SECRET');
const workflow = JSON.parse(readFileSync(SRC, 'utf8'));
workflow.id = WF_ID;
workflow.name = WF_NAME;
workflow.active = false;
for (const node of workflow.nodes) {
  if (node.type !== 'n8n-nodes-base.googleDriveTrigger') continue;
  // Enabling Drive Trigger without a signed-in OAuth client can block
  // workflow activation (and the webhook). Keep them off unless both the
  // folder and Google OAuth client env vars are present.
  if (folder && folder !== PLACEHOLDER && googleReady) {
    if (node.parameters?.folderToWatch) {
      node.parameters.folderToWatch.value = folder;
    }
    node.disabled = false;
  } else {
    if (folder && folder !== PLACEHOLDER && node.parameters?.folderToWatch) {
      node.parameters.folderToWatch.value = folder;
    }
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
    const byName = database.prepare(
      'SELECT id, active FROM workflow_entity WHERE name = ? ORDER BY active DESC LIMIT 1',
    ).get(WF_NAME);
    if (byName?.id) return byName;
    return database.prepare(
      'SELECT id, active FROM workflow_entity WHERE id = ? LIMIT 1',
    ).get(WF_ID);
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
const liveCredIds = live && db ? credentialIdsFromWorkflow(db, live.id) : {};
if (live && db) {
  try {
    retargetWorkflowCreds(workflow.nodes, liveCredIds);
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
      folder && folder !== PLACEHOLDER && googleReady
        ? 'save5hours: patched workflow Drive folder from GEMINI_NOTES_FOLDER_ID'
        : 'save5hours: Drive triggers disabled until folder ID + Google OAuth client exist',
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
  try {
    upsertCredentials(db, creds, projectId, liveCredIds);
    console.log(`save5hours: wrote credentials (${creds.map((c) => c.name).join(', ')})`);
  } catch (error) {
    console.error('save5hours: credential write failed; paste them in the n8n Credentials UI', error.message);
  }
}

closeDb();

const canActivate = envPresent('OPENROUTER_API_KEY') && envPresent('NOTION_API_KEY')
  && process.env.N8N_ACTIVATE_WORKFLOW === 'true';
if (canActivate) {
  const activateId = live?.id || WF_ID;
  // CLI `update:workflow --active true` hits SQLITE FK 787 when the row is
  // already active. n8n then activates active=1 workflows on process start.
  if (Number(live?.active) === 1) {
    console.log('save5hours: workflow already active', activateId);
  } else {
    console.log('save5hours: activating workflow', activateId);
    run(['n8n', 'update:workflow', '--id', activateId, '--active', 'true']);
  }
}

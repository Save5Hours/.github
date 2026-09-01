import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  PEOPLE,
  buildNotionPage,
  driveCallerAllowed,
  extractJson,
  extractPublicDrivePayload,
  mapAssignee,
  normalizeMeetingInput,
  noteTextIsReady,
  parseDriveFileId,
  parseHqDriveConfirmation,
  parseOpenRouterContent,
  skipDuplicateTasks,
} from '../lib/transform.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('Ronald maps to Roman HQ user, not Gmail', () => {
  const mapped = mapAssignee('Ronald');
  assert.equal(mapped.key, 'roman');
  assert.equal(mapped.id, PEOPLE.roman);
});

test('unknown owner defaults to Antoine', () => {
  assert.equal(mapAssignee('someone else').key, 'antoine');
});

test('empty Gemini doc is not ready; paella notes are', () => {
  assert.equal(noteTextIsReady('Notes from Gemini\n'), false);
  const notes = readFileSync(join(root, 'fixtures/paella-notes.txt'), 'utf8');
  assert.equal(noteTextIsReady(notes), true);
});

test('Apps Script VERIFY_NOTES matches drive-verify fixture', () => {
  const notes = readFileSync(join(root, 'fixtures/drive-verify-notes.txt'), 'utf8').trim();
  const src = readFileSync(join(root, 'scripts/apps-script-drive-webhook.js'), 'utf8');
  assert.match(src, /function verifyDrivePath\(/);
  assert.match(src, /WEBHOOK_SECRET_PASTE/);
  assert.match(src, /ScriptApp\.getOAuthToken/);
  assert.match(src, /meeting-notes-drive/);
  assert.match(src, /googleAccessToken/);
  for (const line of notes.split('\n').filter(Boolean)) {
    assert.ok(src.includes(line), line);
  }
});

test('parseDriveFileId reads Google Doc URLs and rejects inline ids', () => {
  assert.equal(
    parseDriveFileId('https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit'),
    '1DocVerifyFileIdNotInline99',
  );
  assert.equal(
    parseDriveFileId('https://docs.google.com/document/u/0/d/1DocVerifyFileIdNotInline99/edit'),
    '1DocVerifyFileIdNotInline99',
  );
  assert.equal(
    parseDriveFileId('https://drive.google.com/open?id=1DocVerifyFileIdNotInline99'),
    '1DocVerifyFileIdNotInline99',
  );
  assert.equal(parseDriveFileId('inline-15616df3'), '');
  assert.equal(parseDriveFileId('1BareFileIdFromHqTask'), '1BareFileIdFromHqTask');
});

test('extractPublicDrivePayload reads n8n form POST with fileId + text', () => {
  const notes = readFileSync(join(root, 'fixtures/drive-verify-notes.txt'), 'utf8');
  const fromForm = extractPublicDrivePayload({
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: {
      fileId: '1DocVerifyFileIdNotInline99',
      url: 'https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit',
      name: 'Gemini notes — Drive path verification (n8n)',
      text: notes,
    },
  });
  assert.equal(fromForm.fileId, '1DocVerifyFileIdNotInline99');
  assert.equal(fromForm.hasText, true);
  assert.equal(fromForm.inlineText, notes.trim());
  assert.doesNotMatch(fromForm.fileId, /^inline-/);

  const urlOnly = extractPublicDrivePayload({
    url: 'https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit',
  });
  assert.equal(urlOnly.fileId, '1DocVerifyFileIdNotInline99');
  assert.equal(urlOnly.hasText, false);
  assert.equal(urlOnly.inlineText, '');

  const empty = extractPublicDrivePayload({ body: {} });
  assert.equal(empty.fileId, '');
  assert.equal(empty.hasText, false);

  const fromBodyString = extractPublicDrivePayload({
    body: 'https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit',
  });
  assert.equal(fromBodyString.fileId, '1DocVerifyFileIdNotInline99');

  const fromNotes = extractPublicDrivePayload({
    body: {
      text: `https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit\n\n${notes}`,
    },
  });
  assert.equal(fromNotes.fileId, '1DocVerifyFileIdNotInline99');
  assert.equal(fromNotes.hasText, true);
});

test('parseHqDriveConfirmation reads Notion Drive URL and file ID properties', () => {
  const fromUrl = parseHqDriveConfirmation({
    properties: {
      'Drive URL': { url: 'https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit' },
      'Drive file ID': { rich_text: [] },
      Name: { title: [{ plain_text: 'Confirm the Drive folder' }] },
    },
  });
  assert.equal(fromUrl.fileId, '1DocVerifyFileIdNotInline99');
  assert.equal(fromUrl.hasText, false);

  const empty = parseHqDriveConfirmation({ properties: {} });
  assert.equal(empty.fileId, '');

  const inline = parseHqDriveConfirmation({
    properties: {
      'Drive file ID': { rich_text: [{ plain_text: 'inline-15616df3' }] },
    },
  });
  assert.equal(inline.fileId, '');

  const fromBody = parseHqDriveConfirmation(
    { properties: {} },
    {
      results: [
        {
          type: 'paragraph',
          paragraph: {
            rich_text: [
              {
                plain_text: 'notes: https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit',
                href: 'https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit',
              },
            ],
          },
        },
      ],
    },
  );
  assert.equal(fromBody.fileId, '1DocVerifyFileIdNotInline99');
});

test('driveCallerAllowed is Save 5 Hours plus known organizer Gmail', () => {
  assert.equal(driveCallerAllowed('antoine@save5hours.ch'), true);
  assert.equal(driveCallerAllowed('Roman@Save5Hours.ch'), true);
  assert.equal(driveCallerAllowed('antubejar96@gmail.com'), true);
  assert.equal(driveCallerAllowed('deevlylabs@gmail.com'), true);
  assert.equal(driveCallerAllowed('roman.cajka@gmail.com'), true);
  assert.equal(driveCallerAllowed('stranger@gmail.com'), false);
  assert.equal(driveCallerAllowed(''), false);
});

test('Apps Script payload keeps the real Drive fileId and notes text', () => {
  const notes = readFileSync(join(root, 'fixtures/drive-verify-notes.txt'), 'utf8');
  assert.equal(noteTextIsReady(notes), true);
  const payload = normalizeMeetingInput({
    fileId: '1DriveVerifyFileIdNotInline',
    name: 'Gemini notes — Drive path verification (n8n)',
    mimeType: 'application/vnd.google-apps.document',
    webViewLink: 'https://docs.google.com/document/d/1DriveVerifyFileIdNotInline/edit',
    text: notes,
  });
  assert.equal(payload.fileId, '1DriveVerifyFileIdNotInline');
  assert.equal(payload.inlineText, notes.trim());
  assert.doesNotMatch(payload.fileId, /^inline-/);
});

test('normalizeMeetingInput accepts Drive fileId or inline webhook text', () => {
  const fromDrive = normalizeMeetingInput({
    id: 'abc123',
    name: 'Gemini notes',
    mimeType: 'application/vnd.google-apps.document',
  });
  assert.equal(fromDrive.fileId, 'abc123');
  assert.equal(fromDrive.inlineText, '');

  const fromWebhookBody = normalizeMeetingInput({
    body: { fileId: 'doc-9', name: 'Meet notes' },
  });
  assert.equal(fromWebhookBody.fileId, 'doc-9');

  const notes = readFileSync(join(root, 'fixtures/paella-notes.txt'), 'utf8');
  const inline = normalizeMeetingInput({ body: { text: notes, name: 'Team lunch' } });
  assert.equal(inline.name, 'Team lunch');
  assert.match(inline.fileId, /^inline-/);
  assert.equal(inline.mimeType, 'text/plain');
  assert.equal(inline.inlineText, notes.trim());
  assert.equal(
    normalizeMeetingInput({ body: { text: notes, name: 'Team lunch' } }).fileId,
    inline.fileId,
  );

  assert.throws(() => normalizeMeetingInput({}), /fileId or notes text/);
});

test('paella fixture becomes three HQ Tasks payloads', () => {
  const llm = JSON.parse(readFileSync(join(root, 'fixtures/paella-openrouter.json'), 'utf8'));
  const parsed = parseOpenRouterContent(JSON.stringify(llm), {
    fileId: 'drive-file-paella',
    fileName: 'Gemini notes — team lunch',
    webViewLink: 'https://docs.google.com/document/d/drive-file-paella/edit',
  });

  assert.equal(parsed.taskCount, 3);
  assert.deepEqual(
    parsed.tasks.map((t) => [t.title, t.assignee, t.assigneeId]),
    [
      ['Make a paella', 'roman', PEOPLE.roman],
      ['Bring the beers', 'antoine', PEOPLE.antoine],
      ['Bring the cheese', 'martin', PEOPLE.martin],
    ],
  );

  const pages = parsed.tasks.map(buildNotionPage);
  assert.equal(pages[0].parent.database_id, '3bc0b26fcc4e8057b7ade1cdf5a67e6e');
  assert.equal(pages[0].properties.Origin.select.name, 'Meeting');
  assert.equal(pages[0].properties.Status.status.name, 'Not started');
  assert.equal(pages[0].properties.Assignee.people[0].id, PEOPLE.roman);
  assert.equal(pages[1].properties.Assignee.people[0].id, PEOPLE.antoine);
  assert.equal(pages[2].properties.Assignee.people[0].id, PEOPLE.martin);
  assert.equal(pages[0].properties['Drive file ID'].rich_text[0].text.content, 'drive-file-paella');
});

test('extractJson accepts fenced OpenRouter output', () => {
  const parsed = extractJson('Here you go:\n```json\n{"meeting_title":"x","tasks":[]}\n```');
  assert.equal(parsed.meeting_title, 'x');
});

test('skipDuplicateTasks drops titles already in Notion for that Drive file', () => {
  const parsed = {
    tasks: [
      { title: 'Make a paella' },
      { title: 'Bring the beers' },
    ],
  };
  const query = {
    results: [
      { properties: { Name: { title: [{ plain_text: 'Make a paella' }] } } },
    ],
  };
  const next = skipDuplicateTasks(parsed, query);
  assert.equal(next.skipped, 1);
  assert.equal(next.taskCount, 1);
  assert.equal(next.tasks[0].title, 'Bring the beers');
});

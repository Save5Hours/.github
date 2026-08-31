import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  PEOPLE,
  buildNotionPage,
  extractJson,
  mapAssignee,
  noteTextIsReady,
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

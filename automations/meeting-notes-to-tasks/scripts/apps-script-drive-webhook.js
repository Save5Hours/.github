/**
 * Walk a Drive folder tree (Meet Recordings) and POST Gemini Google Docs
 * to the n8n webhook **with the document text**.
 *
 * Use this when notes sit in per-meeting subfolders (Drive Trigger does not
 * watch children). Sending `text` means n8n does not need Google OAuth for
 * this path — only OpenRouter + Notion + this webhook secret.
 *
 * Gemini often creates an empty Doc first, then fills it. This script uses
 * lastUpdated and skips notes shorter than 80 characters.
 *
 * Setup (Workspace admin / Meet organizer):
 * 1. https://script.google.com → New project
 * 2. Paste this file
 * 3. Project Settings → Script properties:
 *      WEBHOOK_URL     https://n8n-production-192e.up.railway.app/webhook/meeting-notes
 *      WEBHOOK_SECRET  same value as n8n Header Auth "Meeting notes webhook secret"
 *      FOLDER_ID       optional; Drive folder id
 *      FOLDER_NAME     optional; default "Meet Recordings" if FOLDER_ID is empty
 * 4. Run **installMinuteTrigger** once (creates the 1-minute trigger).
 * 5. Optional: run **listCandidateFolders** and paste a folder URL on the HQ Drive task.
 *
 * The n8n workflow must be Active. Header name is X-Webhook-Secret.
 */
var MIN_NOTE_CHARS = 80;
var DEFAULT_WEBHOOK =
  "https://n8n-production-192e.up.railway.app/webhook/meeting-notes";
var DEFAULT_FOLDER_NAME = "Meet Recordings";

function installMinuteTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === "checkNewMeetingNotes") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger("checkNewMeetingNotes").timeBased().everyMinutes(1).create();
}

function listCandidateFolders() {
  ["Meet Recordings", "Gemini meeting notes", "Gemini notes"].forEach(function (name) {
    const it = DriveApp.getFoldersByName(name);
    while (it.hasNext()) {
      const folder = it.next();
      Logger.log(name + " " + folder.getId() + " " + folder.getUrl());
    }
  });
}

function checkNewMeetingNotes() {
  const props = PropertiesService.getScriptProperties();
  const webhookUrl = props.getProperty("WEBHOOK_URL") || DEFAULT_WEBHOOK;
  const secret = required_(props, "WEBHOOK_SECRET");
  const folder = resolveFolder_(props);

  const lastIso =
    props.getProperty("lastChecked") ||
    new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
  const lastMs = Date.parse(lastIso);
  const nowIso = new Date().toISOString();
  const docs = [];

  walkFolder_(folder, docs);

  docs.forEach(function (file) {
    if (file.getMimeType() !== MimeType.GOOGLE_DOCS) return;
    if (file.getLastUpdated().getTime() <= lastMs) return;

    const text = DocumentApp.openById(file.getId()).getBody().getText();
    const compact = String(text || "").replace(/\s+/g, " ").trim();
    if (compact.length < MIN_NOTE_CHARS) return;

    const fp = fingerprint_(compact);
    const fpKey = "fp_" + file.getId();
    if (props.getProperty(fpKey) === fp) return;

    const response = UrlFetchApp.fetch(webhookUrl, {
      method: "post",
      contentType: "application/json",
      headers: { "X-Webhook-Secret": secret },
      payload: JSON.stringify({
        fileId: file.getId(),
        name: file.getName(),
        mimeType: file.getMimeType(),
        webViewLink: file.getUrl(),
        text: text,
      }),
      muteHttpExceptions: true,
    });

    const code = response.getResponseCode();
    if (code >= 200 && code < 300) {
      props.setProperty(fpKey, fp);
    }
  });

  props.setProperty("lastChecked", nowIso);
}

function resolveFolder_(props) {
  const folderId = props.getProperty("FOLDER_ID");
  if (folderId) return DriveApp.getFolderById(folderId);
  const name = props.getProperty("FOLDER_NAME") || DEFAULT_FOLDER_NAME;
  const it = DriveApp.getFoldersByName(name);
  if (!it.hasNext()) {
    throw new Error(
      "Drive folder not found. Set script property FOLDER_ID or FOLDER_NAME (tried: " +
        name +
        ").",
    );
  }
  return it.next();
}

function walkFolder_(folder, acc) {
  const files = folder.getFiles();
  while (files.hasNext()) acc.push(files.next());
  const subs = folder.getFolders();
  while (subs.hasNext()) walkFolder_(subs.next(), acc);
}

function fingerprint_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text)
    .map(function (b) {
      const v = b < 0 ? b + 256 : b;
      return ("0" + v.toString(16)).slice(-2);
    })
    .join("");
}

function required_(props, key) {
  const value = props.getProperty(key);
  if (!value) throw new Error("Missing script property: " + key);
  return value;
}

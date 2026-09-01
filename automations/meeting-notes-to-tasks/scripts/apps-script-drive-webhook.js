/**
 * Walk a Drive folder tree (Meet Recordings) and POST Gemini Google Docs
 * to the n8n webhook **with the document text**.
 *
 * Use this when notes sit in per-meeting subfolders (Drive Trigger does not
 * watch children). Sending `text` means n8n does not need Google OAuth for
 * this path — only OpenRouter + Notion. Auth is the Google token from
 * ScriptApp.getOAuthToken() (Save 5 Hours / known organizer emails).
 *
 * Gemini often creates an empty Doc first, then fills it. This script uses
 * lastUpdated and skips notes shorter than 80 characters.
 *
 * Setup (Workspace admin / Meet organizer) — no n8n login:
 * 1. https://script.google.com → New project → paste this file
 * 2. Run **verifyDrivePath** once (creates a real Google Doc, POSTs
 *    {fileId,text} to /webhook/public-drive-doc first — no n8n userinfo —
 *    then /webhook/meeting-notes-drive if that fails, installs the trigger).
 *    Log: FOLDER_URL / FILE_ID → HQ Drive task.
 * Optional Script properties: FOLDER_ID, FOLDER_NAME, WEBHOOK_URL.
 * Optional WEBHOOK_SECRET_PASTE / WEBHOOK_SECRET only if you point WEBHOOK_URL
 * at /webhook/meeting-notes (Header Auth). The default Drive path does not.
 *
 * Keep VERIFY_NOTES in sync with fixtures/drive-verify-notes.txt.
 * The n8n workflow must be Active.
 */
var MIN_NOTE_CHARS = 80;
var PUBLIC_WEBHOOK =
  "https://n8n-production-192e.up.railway.app/webhook/public-drive-doc";
var DEFAULT_WEBHOOK =
  "https://n8n-production-192e.up.railway.app/webhook/meeting-notes-drive";
var DEFAULT_FOLDER_NAME = "Meet Recordings";
// Optional. Only needed for /webhook/meeting-notes (Header Auth), not the default URL.
var WEBHOOK_SECRET_PASTE = "";
var VERIFY_FOLDER_NAME = "Gemini meeting notes (n8n)";
var VERIFY_DOC_NAME = "Gemini notes — Drive path verification (n8n)";
var VERIFY_NOTES =
  "Gemini notes — Drive path verification (n8n)\n\n" +
  "Attendees: Antoine Bejarano Alvarez, Martin, Roman Cajka.\n\n" +
  "Actions agreed:\n" +
  "- Antoine will publish the Drive webhook runbook in HQ this week.\n" +
  "- Martin will review HQ Tasks with Origin Meeting after the Drive file lands.\n" +
  "- Roman will confirm the Meet Recordings folder URL on the Drive confirmation task.\n";

function installMinuteTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === "checkNewMeetingNotes") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger("checkNewMeetingNotes").timeBased().everyMinutes(1).create();
}

function listCandidateFolders() {
  [DEFAULT_FOLDER_NAME, "Gemini meeting notes", VERIFY_FOLDER_NAME].forEach(
    function (name) {
      const it = DriveApp.getFoldersByName(name);
      while (it.hasNext()) {
        const folder = it.next();
        Logger.log(name + " " + folder.getId() + " " + folder.getUrl());
      }
    },
  );
}

/**
 * One Run: create a real Google Doc, POST {fileId, text} to n8n, install the
 * 1-minute trigger. HQ Tasks must then show a Drive file ID that is not inline-*.
 */
function verifyDrivePath() {
  const props = PropertiesService.getScriptProperties();
  const webhookUrl = props.getProperty("WEBHOOK_URL") || DEFAULT_WEBHOOK;
  const secret = webhookSecret_(props);
  const folder = ensureFolder_(props);

  const doc = DocumentApp.create(VERIFY_DOC_NAME);
  doc.getBody().setText(VERIFY_NOTES);
  doc.saveAndClose();

  const file = DriveApp.getFileById(doc.getId());
  file.moveTo(folder);
  try {
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  } catch (err) {
    Logger.log("share skipped " + err);
  }

  const text = DocumentApp.openById(file.getId()).getBody().getText();
  const code = postNote_(webhookUrl, secret, file, text);
  if (code >= 200 && code < 300) {
    props.setProperty("fp_" + file.getId(), fingerprint_(compact_(text)));
  }

  installMinuteTrigger();
  Logger.log("HTTP " + code);
  Logger.log("FOLDER_ID " + folder.getId());
  Logger.log("FOLDER_URL " + folder.getUrl());
  Logger.log("FILE_ID " + file.getId());
  Logger.log("FILE_URL " + file.getUrl());
  if (code < 200 || code >= 300) {
    throw new Error("n8n webhook HTTP " + code);
  }
}

function checkNewMeetingNotes() {
  const props = PropertiesService.getScriptProperties();
  const webhookUrl = props.getProperty("WEBHOOK_URL") || DEFAULT_WEBHOOK;
  const secret = webhookSecret_(props);
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
    const compact = compact_(text);
    if (compact.length < MIN_NOTE_CHARS) return;

    const fp = fingerprint_(compact);
    const fpKey = "fp_" + file.getId();
    if (props.getProperty(fpKey) === fp) return;

    const code = postNote_(webhookUrl, secret, file, text);
    if (code >= 200 && code < 300) {
      props.setProperty(fpKey, fp);
    }
  });

  props.setProperty("lastChecked", nowIso);
}

function postWithRetry_(url, headers, payload) {
  var attempts = 0;
  var code = 0;
  var body = "";
  while (attempts < 6) {
    attempts++;
    const response = UrlFetchApp.fetch(url, {
      method: "post",
      contentType: "application/json",
      headers: headers,
      payload: payload,
      muteHttpExceptions: true,
    });
    code = response.getResponseCode();
    body = String(response.getContentText() || "");
    if (code >= 200 && code < 300) return code;
    const retryable =
      code === 404 ||
      code === 502 ||
      code === 503 ||
      /not registered/i.test(body);
    if (!retryable || attempts >= 6) return code;
    Utilities.sleep(10000);
  }
  return code;
}

function postNote_(webhookUrl, secret, file, text) {
  const publicPayload = JSON.stringify({
    fileId: file.getId(),
    url: file.getUrl(),
    name: file.getName(),
    mimeType: file.getMimeType(),
    webViewLink: file.getUrl(),
    text: text,
  });
  // Prefer public-drive-doc: fileId+text goes to OpenRouter without Google userinfo.
  const publicCode = postWithRetry_(PUBLIC_WEBHOOK, {}, publicPayload);
  if (publicCode >= 200 && publicCode < 300) return publicCode;

  const token = ScriptApp.getOAuthToken();
  const headers = { Authorization: "Bearer " + token };
  const pasted = String(secret || "").trim();
  if (pasted) headers["X-Webhook-Secret"] = pasted;
  const payload = JSON.stringify({
    fileId: file.getId(),
    name: file.getName(),
    mimeType: file.getMimeType(),
    webViewLink: file.getUrl(),
    text: text,
    googleAccessToken: token,
  });
  return postWithRetry_(webhookUrl, headers, payload);
}

function ensureFolder_(props) {
  try {
    return resolveFolder_(props);
  } catch (err) {
    const folder = DriveApp.createFolder(VERIFY_FOLDER_NAME);
    props.setProperty("FOLDER_ID", folder.getId());
    return folder;
  }
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

function compact_(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function fingerprint_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text)
    .map(function (b) {
      const v = b < 0 ? b + 256 : b;
      return ("0" + v.toString(16)).slice(-2);
    })
    .join("");
}

function webhookSecret_(props) {
  const pasted = String(WEBHOOK_SECRET_PASTE || "").trim();
  if (pasted) return pasted;
  return String(props.getProperty("WEBHOOK_SECRET") || "").trim();
}

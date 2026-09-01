/**
 * Connect Drive to self-hosted n8n WITHOUT Google Cloud Console.
 *
 * n8n Cloud has a Google Sign-in button. Railway n8n does not. This script
 * uses Google's own login (script.google.com → Run → Allow).
 *
 * Setup (Meet organizer Google account):
 * 1. https://script.google.com → New project → paste this file
 * 2. Run verifyDrivePath → click Allow for Drive + Docs (once)
 * 3. Run backfillAllMeetingNotes → sends every existing Doc in the folder
 * 4. Leave the 1-minute trigger on (installMinuteTrigger) for new meetings
 *
 * It POSTs { fileId, text, googleAccessToken } to /webhook/meeting-notes-drive.
 * n8n checks the Google email against the Save 5 Hours allowlist.
 * No WEBHOOK_SECRET. No Client ID. No redirect URI.
 */
var MIN_NOTE_CHARS = 80;
var DEFAULT_WEBHOOK =
  "https://n8n-production-192e.up.railway.app/webhook/meeting-notes-drive";
var DEFAULT_FOLDER_NAME = "Meet Recordings";
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
  const lastIso =
    PropertiesService.getScriptProperties().getProperty("lastChecked") ||
    new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
  syncFolderDocs_({
    sinceMs: Date.parse(lastIso),
    limit: 20,
    sleepMs: 0,
    skipVerifyDocs: true,
  });
  PropertiesService.getScriptProperties().setProperty(
    "lastChecked",
    new Date().toISOString(),
  );
}

/** One-time: every Google Doc already in Meet Recordings (and subfolders). */
function backfillAllMeetingNotes() {
  const result = syncFolderDocs_({
    sinceMs: 0,
    limit: 25,
    sleepMs: 2000,
    skipVerifyDocs: true,
  });
  installMinuteTrigger();
  if (result.remaining === 0 && result.failed === 0) {
    PropertiesService.getScriptProperties().setProperty(
      "lastChecked",
      new Date().toISOString(),
    );
  }
  Logger.log("BACKFILL scanned=" + result.scanned);
  Logger.log("BACKFILL posted=" + result.posted);
  Logger.log("BACKFILL skipped=" + result.skipped);
  Logger.log("BACKFILL failed=" + result.failed);
  Logger.log("BACKFILL remaining=" + result.remaining);
  if (result.remaining > 0) {
    Logger.log("Run backfillAllMeetingNotes again for the rest.");
  }
}

function syncFolderDocs_(opts) {
  const props = PropertiesService.getScriptProperties();
  const webhookUrl = props.getProperty("WEBHOOK_URL") || DEFAULT_WEBHOOK;
  const secret = webhookSecret_(props);
  const folder = resolveFolder_(props);
  const sinceMs = Number(opts.sinceMs || 0);
  const limit = Number(opts.limit || 25);
  const sleepMs = Number(opts.sleepMs || 0);
  const skipVerify = opts.skipVerifyDocs !== false;
  const docs = [];
  walkFolder_(folder, docs);

  const result = { scanned: 0, posted: 0, skipped: 0, failed: 0, remaining: 0 };
  const pending = [];

  docs.forEach(function (file) {
    if (file.getMimeType() !== MimeType.GOOGLE_DOCS) return;
    result.scanned += 1;
    const name = String(file.getName() || "");
    if (skipVerify && name.indexOf(VERIFY_DOC_NAME) === 0) {
      result.skipped += 1;
      return;
    }
    if (sinceMs && file.getLastUpdated().getTime() <= sinceMs) {
      result.skipped += 1;
      return;
    }
    pending.push(file);
  });

  pending.forEach(function (file) {
    if (result.posted + result.failed >= limit) {
      result.remaining += 1;
      return;
    }

    const text = DocumentApp.openById(file.getId()).getBody().getText();
    const compact = compact_(text);
    if (compact.length < MIN_NOTE_CHARS) {
      result.skipped += 1;
      return;
    }

    const fp = fingerprint_(compact);
    const fpKey = "fp_" + file.getId();
    if (props.getProperty(fpKey) === fp) {
      result.skipped += 1;
      return;
    }

    const code = postNote_(webhookUrl, secret, file, text);
    Logger.log("HTTP " + code + " " + file.getName() + " " + file.getId());
    if (code >= 200 && code < 300) {
      props.setProperty(fpKey, fp);
      result.posted += 1;
      if (sleepMs > 0) Utilities.sleep(sleepMs);
    } else {
      result.failed += 1;
    }
  });

  props.setProperty("FOLDER_ID", folder.getId());
  return result;
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

/**
 * Optional: walk a Drive folder tree (Meet Recordings) and POST new Google Docs
 * to the n8n webhook. Use this when notes sit in per-meeting subfolders.
 *
 * Setup (Workspace admin / Meet organizer):
 * 1. https://script.google.com → New project
 * 2. Paste this file
 * 3. Project Settings → Script properties:
 *      FOLDER_ID          Meet Recordings (or parent) folder id
 *      WEBHOOK_URL        https://YOUR-N8N-HOST/webhook/meeting-notes
 *      WEBHOOK_SECRET     same value as n8n Header Auth "Meeting notes webhook secret"
 * 4. Enable Drive API (Services → Drive API) if you prefer Drive.Files; DriveApp is enough
 * 5. Triggers → Add trigger → checkNewMeetingNotes → Time-driven → Every minute
 *
 * The n8n workflow must be Published. Header name is X-Webhook-Secret.
 */
function checkNewMeetingNotes() {
  const props = PropertiesService.getScriptProperties();
  const folderId = required_(props, "FOLDER_ID");
  const webhookUrl = required_(props, "WEBHOOK_URL");
  const secret = required_(props, "WEBHOOK_SECRET");

  const lastIso = props.getProperty("lastChecked") || new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
  const lastMs = Date.parse(lastIso);
  const nowIso = new Date().toISOString();
  const docs = [];

  walkFolder_(DriveApp.getFolderById(folderId), docs);

  docs.forEach(function (file) {
    if (file.getMimeType() !== MimeType.GOOGLE_DOCS) return;
    if (file.getDateCreated().getTime() <= lastMs) return;

    UrlFetchApp.fetch(webhookUrl, {
      method: "post",
      contentType: "application/json",
      headers: { "X-Webhook-Secret": secret },
      payload: JSON.stringify({
        fileId: file.getId(),
        name: file.getName(),
        mimeType: file.getMimeType(),
        webViewLink: file.getUrl(),
      }),
      muteHttpExceptions: true,
    });
  });

  props.setProperty("lastChecked", nowIso);
}

function walkFolder_(folder, acc) {
  const files = folder.getFiles();
  while (files.hasNext()) acc.push(files.next());
  const subs = folder.getFolders();
  while (subs.hasNext()) walkFolder_(subs.next(), acc);
}

function required_(props, key) {
  const value = props.getProperty(key);
  if (!value) throw new Error("Missing script property: " + key);
  return value;
}

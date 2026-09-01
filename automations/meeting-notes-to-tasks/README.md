# Meeting notes → HQ Tasks (n8n on Railway)

Gemini / Google Meet notes land in Drive as Google Docs. n8n reads each new doc, sends the text to **OpenRouter** (`openrouter/free`), and creates one HQ **Tasks** row per action item, assigned to Antoine, Martin, or Roman.

```
Google Meet ends
  → Gemini notes Google Doc in a flat Drive folder
    → n8n (Railway) polls that folder once a minute
      → OpenRouter extracts action items
        → Notion HQ Tasks (Assignee + Origin=Meeting)
```

**Live n8n (1.123.75):** [https://n8n-production-192e.up.railway.app/](https://n8n-production-192e.up.railway.app/)  
Account: `deevlylabs@gmail.com`. OpenRouter and Notion already work.

The live canvas is the cleaned 27-node workflow. OpenRouter and Notion already work.

Self-hosted n8n has **no** Google Sign-in button (that exists only on n8n Cloud). Do **not** use Drive-setup, Colab, gcloud codes, or bookmarklets.

## Connect Google without Cloud Console (do this)

Google Apps Script uses the Google account you already have. No Client ID. No redirect URI.

**Live Apps Script (Drive watcher):** [project `1hM320L8wvgULoPY1vEvAoLdTynmnJMYxIKX7w6WSuPKVC3rKkvyz4okw`](https://script.google.com/home/projects/1hM320L8wvgULoPY1vEvAoLdTynmnJMYxIKX7w6WSuPKVC3rKkvyz4okw/edit)

1. Open that project signed in as the Meet organizer (or [script.google.com](https://script.google.com) → New project).
2. Paste [`apps-script-drive-webhook.js`](https://raw.githubusercontent.com/Save5Hours/.github/cursor/fix-drive-notion-automation-007c/automations/meeting-notes-to-tasks/scripts/apps-script-drive-webhook.js) (replace the old file).
3. Run **verifyDrivePath** once (Allow Drive + Docs).
4. Run **backfillAllMeetingNotes** once. That POSTs every existing Google Doc in `Meet Recordings` (subfolders included). If the log says `remaining>0`, run it again.
5. Run **installMinuteTrigger** once (checks Drive every **5 minutes**). New or updated Docs go to n8n by themselves. n8n only executes when a Doc is posted — empty checks appear in script.google.com → Executions, not in n8n.

n8n skips action titles that already exist for the same Drive file ID. Verification Docs named `Gemini notes — Drive path verification` are skipped on backfill.

## Optional later: native Drive Trigger (needs Google Cloud Console)

n8n Cloud users click **Sign in with Google**. Self-hosted users must create a **Custom OAuth2** app ([n8n docs](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/)):

1. [Google Cloud Console](https://console.cloud.google.com/) → new project → enable **Drive API** + **Docs API**.
2. OAuth consent → **Internal** (Workspace).
3. Credentials → OAuth client ID → **Web application**.
4. Redirect URI from the n8n credential panel (must match exactly), typically:

   `https://n8n-production-192e.up.railway.app/rest/oauth2-credential/callback`
5. Paste Client ID + Secret into n8n **Google Drive (Save 5 Hours)** → **Sign in with Google**.
6. Put the folder ID on both Drive Trigger nodes. Notes must sit **directly** in that folder.

Service accounts are a worse fit here (no My Drive quota; Drive Trigger wants OAuth2).

## Import this cleaned workflow

Overwrite the **open** workflow (not a new copy). ⋮ → **Import from URL**:

`https://raw.githubusercontent.com/Save5Hours/.github/cursor/fix-drive-notion-automation-007c/automations/meeting-notes-to-tasks/n8n/meeting-notes-to-tasks.json`

Map existing credentials:

- `Google Drive (Save 5 Hours)`
- `Notion (Save 5 Hours HQ)`
- `OpenRouter`
- `Meeting notes webhook secret`

Keep the existing credentials. Do not rotate `N8N_ENCRYPTION_KEY`. Do not drop the Railway volume.

## Nested Meet Recordings folders

The Apps Script path already walks subfolders. If you later switch to native Drive Trigger, put shortcuts into the watched folder — the trigger does not see children.

## Webhook dry-run (optional)

```bash
curl -sS -X POST "https://n8n-production-192e.up.railway.app/webhook/meeting-notes" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{"text":"Antoine brings beers. Martin brings cheese. Roman makes paella."}'
```

That path writes `Drive file ID = inline-*`. A real Drive run uses a Google Doc id.

## What gets written to Notion

| Property | Value |
| --- | --- |
| Name | Action title in English |
| Assignee | Antoine / Martin / Roman (`ronald` → Roman) |
| Status | `Not started` |
| Priority | High / Medium / Low |
| Origin | `Meeting` |
| Due date | If the model finds a date |
| Drive file ID / Drive URL | Idempotency + backlink |

Unclear owner → Antoine. Re-running the same Drive file skips titles that already exist for that file ID.

## Railway (already done)

Pin **n8n 1.123.75**. `N8N_PORT=5678`. Volume `/home/node/.n8n`. Never rotate `N8N_ENCRYPTION_KEY`. Do not set `N8N_LICENSE_ACTIVATION_KEY`.

HQ runbook: [Meeting notes → HQ Tasks (n8n)](https://app.notion.com/p/3cd0b26fcc4e81cd9441f9420d6d00da)

## Rollback

Unpublish the workflow in n8n. Meeting-origin tasks already in Notion stay until you delete them. Restoring the Railway volume keeps credentials; rotating the encryption key does not.

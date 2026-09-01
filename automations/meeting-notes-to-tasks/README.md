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
Account: `deevlylabs@gmail.com`. OpenRouter and Notion already work (a webhook dry-run wrote HQ Tasks). **Google Drive Sign in is the only missing step.**

Do **not** use the old Drive-setup page, Colab, gcloud verification codes, or bookmarklets. Those were workarounds from a previous agent. The real path is n8n Google Drive OAuth.

## What still works

| Piece | Status |
| --- | --- |
| n8n on Railway | Live, volume `/home/node/.n8n` |
| OpenRouter | Live |
| Notion HQ Tasks | Live |
| Google Drive OAuth | **You click Sign in** (this agent cannot) |
| Drive folder ID | Paste on both Drive Trigger nodes after Sign in |

## Connect Google (do this once)

1. Open [n8n](https://n8n-production-192e.up.railway.app/) and log in.
2. Left sidebar → **Credentials**.
3. Open **Google Drive (Save 5 Hours)** (or create **Google Drive OAuth2 API** with that name).
4. If Client ID / Secret are empty, create them in [Google Cloud Console](https://console.cloud.google.com/):
   - Enable **Google Drive API** and **Google Docs API**.
   - OAuth consent screen → **Internal** (Workspace).
   - Credentials → OAuth client ID → **Web application**.
   - Authorized redirect URI (copy exactly):

     `https://n8n-production-192e.up.railway.app/rest/oauth2-credential/callback`
   - Paste Client ID and Client Secret into the n8n credential.
5. Click **Sign in with Google**. Use the Meet organizer account (`@save5hours.ch` or the Gmail that owns the Gemini notes).
6. Allow Drive + Docs.
7. In Drive, open the notes folder. The URL looks like `https://drive.google.com/drive/folders/THE_FOLDER_ID`. Copy `THE_FOLDER_ID`.
8. Open workflow **Meeting notes → HQ Tasks**. On **both** nodes **Google Drive Trigger** and **Google Drive Trigger (updated)**, paste that folder ID. Notes must sit **directly** in that folder (the trigger does not see Meet Recordings subfolders). Shortcuts into the folder are OK.
9. Save. Make sure the workflow is **Active**.

Then drop a Google Doc in that folder (or wait for the next Meet). Check **Executions**. HQ Tasks should appear with Origin = Meeting.

## Import this cleaned workflow

The live instance may still have the old 50-node workaround graph. After this PR is on the branch, import `n8n/meeting-notes-to-tasks.json` (Workflows → Import from File) and map:

- `Google Drive (Save 5 Hours)`
- `Notion (Save 5 Hours HQ)`
- `OpenRouter`
- `Meeting notes webhook secret`

Keep the existing credentials. Do not rotate `N8N_ENCRYPTION_KEY`. Do not drop the Railway volume.

## Nested Meet Recordings folders (optional)

If Gemini keeps writing `Meet Recordings / <meeting> / notes`, either:

- Put a shortcut to each Doc in the flat folder n8n watches, or
- Deploy `scripts/apps-script-drive-webhook.js` as the Meet organizer. It walks subfolders and POSTs `{ fileId, text }` to `/webhook/meeting-notes` (needs the webhook secret).

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

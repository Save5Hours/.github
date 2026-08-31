# Meeting notes → HQ Tasks (n8n on Railway)

Gemini / Google Meet notes land in Drive as Google Docs. n8n reads each new doc, sends the text to **OpenRouter** (`openrouter/free`), and creates one HQ **Tasks** row per action item, assigned to Antoine, Martin, or Roman.

This is the right architecture. Drive does **not** POST a native webhook when Gemini saves a file. Use n8n’s **Google Drive Trigger** (poll) on a flat folder, or the optional Apps Script → n8n Webhook path if notes stay nested under Meet Recordings.

Gemini often **creates an empty Doc first** and writes the summary afterwards. The workflow therefore watches **file created** and **file updated**, and it skips notes shorter than 80 characters so the later update becomes the real run.

```
Google Meet ends
  → Gemini notes Google Doc in Drive
    → n8n (Railway)
      → OpenRouter (free model router)
        → Notion HQ Tasks (Assignee + Origin=Meeting)
```

Example: notes say Roman makes paella, Antoine brings beers, Martin brings cheese → three tasks on the **By person** board.

**Live n8n (1.123.75):** [https://n8n-production-192e.up.railway.app/](https://n8n-production-192e.up.railway.app/) — Railway project `save5hours-n8n`. Workflow **Meeting notes → HQ Tasks** is Active. OpenRouter + Notion already wrote HQ Tasks from a webhook dry-run (`Drive file ID` = `inline-*`). Remaining: a real Google Doc. Run **`verifyDrivePath`** in `scripts/apps-script-drive-webhook.js` (one Run: creates a Doc, POSTs `{ fileId, text }` to `/webhook/meeting-notes`, installs the 1-minute trigger). Do not re-POST the paella fixture.

## What you paste where

Secrets never go in this Git repo. There are two places:

| Place | What belongs there |
| --- | --- |
| **Railway → n8n service → Variables** | Hosting: `N8N_ENCRYPTION_KEY`, `N8N_HOST`, `WEBHOOK_URL`, timezone. Optional API keys: `OPENROUTER_API_KEY`, `NOTION_API_KEY`, `N8N_WEBHOOK_SECRET`, `GEMINI_NOTES_FOLDER_ID` (boot provision writes n8n credentials). |
| **n8n editor → Credentials** | Same keys if you prefer the UI. Google Drive OAuth still needs **Sign in** here. |

Do not commit secrets. Do not set `N8N_LICENSE_ACTIVATION_KEY`.

---

## 1. Railway (host n8n)

Use **n8n 1.123.x**, not `latest` / 2.x: this workflow’s Code nodes need the 1.x image (2.x wants a separate task-runner service). The live Railway project is already on `n8nio/n8n:1.123.75`.

### Option A — Docker image `n8nio/n8n:1.123.75` (recommended)

1. [railway.app](https://railway.app) → New project → **+ New** → **Docker Image** → `n8nio/n8n:1.123.75`
2. Generate a public domain.
3. Set `WEBHOOK_URL=https://YOUR-SERVICE.up.railway.app/`
4. Set `N8N_PORT=5678` (and point the Railway domain at port **5678**). Do **not** set `N8N_PORT=${{PORT}}` via the CLI — it interpolates empty and n8n binds port 0.
5. Set `N8N_ENCRYPTION_KEY` (`openssl rand -hex 32`) **once**. Never rotate it.
6. Volume at `/home/node/.n8n` (required).
7. Open the URL, create the owner account, keep it private.
8. Import `n8n/meeting-notes-to-tasks.json` (see section 3). For a dry run, put a Google Doc ID on **Set test fileId** and click **Manual test**.

Do **not** use [railway.com/deploy/n8n-latest](https://railway.com/deploy/n8n-latest) for this workflow: that template is n8n 2.x.

HQ runbook: [Meeting notes → HQ Tasks (n8n)](https://app.notion.com/p/3cd0b26fcc4e81cd9441f9420d6d00da)

### Option B — This repo

The Railway CLI is installed here (`railway 5.45.10`) but not logged in. From your laptop:

1. [railway.app](https://railway.app) → New project → **Empty project**.
2. **+ New** → **GitHub repo** → `Save5Hours/.github`  
   Set **Root Directory** to `automations/meeting-notes-to-tasks` (Dockerfile is already pinned to 1.123.75).
3. **Variables** — copy from `.env.example`. Generate the encryption key first:

   ```bash
   openssl rand -hex 32
   ```

   Put that value in `N8N_ENCRYPTION_KEY` **before the first successful boot**. Do not change it later or every stored credential becomes unreadable.
4. **Volumes** → Add volume → mount path **`/home/node/.n8n`** (1 GB is enough to start).
5. **Settings → Networking → Generate Domain**. Then set:

   - `N8N_HOST` = `your-service.up.railway.app` (host only)
   - `WEBHOOK_URL` = `https://your-service.up.railway.app/`
   - `N8N_PORT` = `${{PORT}}`
   - `N8N_PROTOCOL` = `https`
6. Redeploy. Open the public URL. Create the **owner account** (first visitor). Keep the URL private.

### Option C — CLI or GitHub Actions (once you have a token)

```bash
cd automations/meeting-notes-to-tasks
export N8N_ENCRYPTION_KEY="$(openssl rand -hex 32)"   # save this
railway login          # or: export RAILWAY_TOKEN=...
./scripts/deploy-railway.sh
```

The script creates project `save5hours-n8n`, attaches the volume and sets `N8N_ENCRYPTION_KEY` **before** the first n8n process, then deploys this Dockerfile, generates a domain, and sets `WEBHOOK_URL`. The image imports `n8n/meeting-notes-to-tasks.json` on first boot (workflow stays inactive until you add credentials and activate it). Optional: `RAILWAY_WORKSPACE`.

Or add GitHub secrets `RAILWAY_TOKEN` + `N8N_ENCRYPTION_KEY` and run **Actions → Deploy n8n to Railway → Run workflow**.

A project/account token can be exported as `RAILWAY_TOKEN` for CI. Do not commit it.

### Optional Postgres

SQLite on the volume works for a small team. Add Railway Postgres later and the `DB_POSTGRESDB_*` variables in `.env.example` if execution volume grows. The volume is still required for encryption material.

---

## 2. n8n credentials (you paste these in the editor)

Open **n8n → Credentials**. Create these four. Names should match the workflow import so n8n can map them.

### A. Google Drive (Save 5 Hours)

Used by **Google Drive Trigger** and **Download Google Doc as text**.

1. [Google Cloud Console](https://console.cloud.google.com/) in the Save 5 Hours Workspace.
2. New project (or reuse one) → enable **Google Drive API** and **Google Docs API**.
3. **APIs & Services → OAuth consent screen** → User type **Internal**.
4. **Credentials → Create credentials → OAuth client ID → Web application**.
5. Authorized redirect URI (n8n prints this too):

   `https://YOUR-N8N-HOST/rest/oauth2-credential/callback`

6. Copy Client ID and Client Secret into n8n: **Credentials → Google Drive OAuth2 API**.
7. Sign in as a Workspace user that can read the Gemini notes folder (shared with the Meet organizer is fine).

n8n requests Drive scopes for you. You do not paste a service-account JSON unless you switch the trigger to Service Account.

**Folder ID:** in Drive, open the notes folder → the URL looks like  
`https://drive.google.com/drive/folders/FOLDER_ID`.  
In the **Google Drive Trigger** node, replace `REPLACE_ME_GEMINI_NOTES_FOLDER_ID`.

The Drive Trigger **does not watch subfolders**. Put Gemini notes in that folder directly (shortcuts are OK). If Meet keeps creating a nested folder per meeting, use the Apps Script in `scripts/apps-script-drive-webhook.js` instead of (or in addition to) the Drive Trigger.

### B. Notion (Save 5 Hours HQ)

Used to query and create HQ Tasks. The Notion MCP connection in Cursor is **not** this token.

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration** → Internal.
2. Copy the secret (`ntn_…` or `secret_…`).
3. Open [HQ Tasks](https://app.notion.com/p/3bc0b26fcc4e8057b7ade1cdf5a67e6e) → **…** → **Connections** → connect this integration.
4. n8n → **Credentials → Notion API** → paste the secret.

Database id already in the workflow: `3bc0b26fcc4e8057b7ade1cdf5a67e6e`.

### C. OpenRouter

Used by the **OpenRouter** HTTP node. No OpenAI/Anthropic endpoint.

1. [openrouter.ai/keys](https://openrouter.ai/keys) → create a key (`sk-or-…`).
2. n8n → **Credentials → Header Auth**
   - Name the credential **`OpenRouter`**
   - Header **Name:** `Authorization`
   - Header **Value:** `Bearer sk-or-v1-YOUR_KEY` (include the word `Bearer` and a space)

The workflow calls `https://openrouter.ai/api/v1/chat/completions` with model **`openrouter/free`** (random free model that matches the request). To pin a specific free model, edit the Code node **Build OpenRouter payload** and set e.g. `google/gemma-4-31b-it:free`. Free models rotate; if a model 404s, switch the string. Add a few dollars of credit on OpenRouter only if you later want a paid model.

### D. Meeting notes webhook secret

Used only if you enable the **Webhook** node (Apps Script / curl tests).

1. n8n → **Credentials → Header Auth**
   - Name: **`Meeting notes webhook secret`**
   - Header **Name:** `X-Webhook-Secret`
   - Header **Value:** a long random string (`openssl rand -hex 24`)
2. Send the same header from Apps Script or curl.

Production webhook URL after publish:

`https://YOUR-N8N-HOST/webhook/meeting-notes`

Body:

```json
{ "fileId": "GOOGLE_DOC_FILE_ID", "name": "Gemini notes", "text": "..." }
```

Apps Script sends `fileId` **and** `text` so n8n does not need Google OAuth on this path. `{ "text": "..." }` alone becomes `Drive file ID = inline-*` (dry-run only).

---

## 3. Import and publish the workflow

1. n8n → **Workflows → Import from File** → `n8n/meeting-notes-to-tasks.json`.
2. Map the four credentials when n8n prompts.
3. Set the Drive folder ID on **both** Google Drive Trigger nodes (created + updated).
4. **Save**, then **Publish / Active**.
5. Test with a Google Doc in that folder, or:

```bash
curl -sS -X POST "https://YOUR-N8N-HOST/webhook-test/meeting-notes" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{"fileId":"GOOGLE_DOC_FILE_ID"}'
```

Use `/webhook/meeting-notes` once the workflow is published. Check **Executions** if nothing appears in Notion.

Verified against n8n **1.123.75** (same tag as the Dockerfile): `n8n import:workflow` succeeded with 21 nodes and matching connections. That is not an end-to-end Drive run.

## 4. What gets written to Notion

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

Views: [All tasks](https://app.notion.com/p/3bc0b26fcc4e8057b7ade1cdf5a67e6e), By person, Antoine, Martin, Roman.

## 5. Assignee map

See `config/assignee-map.json`. If you change people, edit that file **and** the **Parse and map assignees** Code node (the workflow does not load the JSON at runtime).

## 6. Meet Recordings subfolders

n8n’s Drive Trigger only sees **direct children** of the watched folder. If Gemini writes `Meet Recordings / <meeting> / notes`, either:

- Create a shared folder `Gemini meeting notes` and save/shortcut docs there, or
- Deploy `scripts/apps-script-drive-webhook.js` bound to the Workspace account. Set `WEBHOOK_SECRET` (and optional `FOLDER_ID`). Run **`verifyDrivePath` once** — it creates a real Google Doc, POSTs `{ fileId, text }` to n8n, and installs the 1-minute trigger. Keep the n8n **Webhook** node published.

## Rollback

Unpublish the workflow in n8n. Tasks already created stay in Notion; delete by Origin=Meeting + Drive file ID if needed. Redeploying Railway without the volume or after changing `N8N_ENCRYPTION_KEY` loses credential access — restore the volume snapshot, do not rotate the key.

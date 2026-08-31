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

## What you paste where

Secrets never go in this Git repo. There are two places:

| Place | What belongs there |
| --- | --- |
| **Railway → n8n service → Variables** | Hosting only: `N8N_ENCRYPTION_KEY`, `N8N_HOST`, `WEBHOOK_URL`, timezone |
| **n8n editor → Credentials** (after the instance is up) | Google Drive OAuth, Notion token, OpenRouter key, webhook header |

OpenRouter, Notion, and Google keys are entered in the **n8n UI**, not as Railway env vars.

---

## 1. Railway (host n8n)

This agent **cannot** log into Railway (`railway whoami` → Unauthorized). Fastest path: one-click template in your browser, then import the workflow JSON from this repo.

### Option A — One-click template (recommended)

[Deploy n8n on Railway](https://railway.com/deploy/n8n-latest)

1. Sign in to Railway in that tab. Wait ~2–3 minutes.
2. Generate a public domain.
3. Set `WEBHOOK_URL=https://YOUR-SERVICE.up.railway.app/`
4. Set `N8N_ENCRYPTION_KEY` (`openssl rand -hex 32`) **once**. Never rotate it.
5. Confirm a volume at `/home/node/.n8n`.
6. Open the URL, create the owner account, keep it private.
7. Import `n8n/meeting-notes-to-tasks.json` (see section 3).

HQ runbook: [Meeting notes → HQ Tasks (n8n)](https://app.notion.com/p/3cd0b26fcc4e81cd9441f9420d6d00da)

### Option B — This repo / Docker image

The Railway CLI is installed here (`railway 5.45.10`) but not logged in. From your laptop:

1. [railway.app](https://railway.app) → New project → **Empty project**.
2. **+ New** → **GitHub repo** → `Save5Hours/.github`  
   Set **Root Directory** to `automations/meeting-notes-to-tasks`.
   Or **+ New** → **Docker Image** → `n8nio/n8n`.
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

### Option C — CLI (once you are logged in)

```bash
cd automations/meeting-notes-to-tasks
railway login          # or: railway login --browserless
# Set N8N_ENCRYPTION_KEY first. Attach volume /home/node/.n8n in the dashboard.
./scripts/deploy-railway.sh
railway domain
```

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
{ "fileId": "GOOGLE_DOC_FILE_ID" }
```

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
- Deploy `scripts/apps-script-drive-webhook.js` bound to the Workspace account, set a 1-minute time trigger, and keep the n8n **Webhook** node published.

## Rollback

Unpublish the workflow in n8n. Tasks already created stay in Notion; delete by Origin=Meeting + Drive file ID if needed. Redeploying Railway without the volume or after changing `N8N_ENCRYPTION_KEY` loses credential access — restore the volume snapshot, do not rotate the key.

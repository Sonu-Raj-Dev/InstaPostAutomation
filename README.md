# SONU AI LAB — AI Instagram command center

**From AI discovery to creation. Automatically.**
Research what's happening in AI → verify it → turn the best story into an Instagram post → approve → publish → deliver resources by DM → measure.

## Run

```powershell
pip install fastapi uvicorn python-multipart requests python-dotenv pillow truststore
python src/dashboard/app.py
```
Open **http://127.0.0.1:8000** (old links like `/#creator` still work).
Slide rendering uses the installed Microsoft Edge or Chrome in headless mode (override with `CMS_BROWSER`).

Tests: `python -m pytest tests -q`

## Deploy to Vercel

1. **vercel.com → Add New → Project → Import** `InstaPostAutomation` (no build settings needed; `vercel.json` covers it).
2. In the project: **Storage → Create → Neon (Postgres)** and **Storage → Create → Blob**, connected to the project (adds `DATABASE_URL` and `BLOB_READ_WRITE_TOKEN`).
3. **Settings → Environment Variables**:
   - `APP_PASSWORD` — your login password (required)
   - `CRON_SECRET` — any long random string (lets Vercel Cron run daily research/build)
   - `INSTAGRAM_ACCOUNT_ID`, `META_APP_ID` (and `META_APP_SECRET` if you have it)
4. **Redeploy**, open the URL, sign in, and paste your Meta token in **Settings** (stored in the database, not in env).
5. Optional: copy your local data once — `set DATABASE_URL=...` then `python scripts/copy_to_cloud.py`.
6. Real-time comment replies: **Settings → Cloud** shows the webhook URL + verify token to add in your Meta app (Webhooks → Instagram → `comments`, `messages`, `messaging_postbacks`).

On Vercel: Postgres replaces SQLite, Vercel Blob stores images, `api/render.js` renders with serverless Chromium, Vercel Cron runs research (~17:30 IST) and the daily build (~19:00 IST), and Instagram webhooks trigger the comment-to-DM flow. Locally everything still runs on SQLite + headless Edge with no login.

## The simple flow (start here)

1. **Create post** → pick one verified tool, or a **Pack** of 2–8 tools (“5 free AI video tools…”).
2. **Review** → bright **3D** slides built from each project's real README screenshots, keyword, caption, and a preview of exactly what commenters get in DM.
3. **Publish** → posts to Instagram and switches on **auto-reply**: comment keyword → private reply with a “Send me the access” button → follow check (“I'm following ✅” button if needed) → the guide arrives as copyable text **plus guide pages as images** (install steps, features, screenshots, link). No links to external doc sites.

**My posts** shows every post, its status and its DM results with an auto-reply switch. Everything else lives under **Advanced**.

## Pages (Advanced)

| Route | What it does |
|---|---|
| `#command` | Three.js map of the pipeline (live job stage, node status from real data), KPIs, schedule, latest creative, activity |
| `#intelligence` | Verified research by category with source, date, verification, usefulness/relevance, suggested format |
| `#creator` | Three-panel studio: research context · live WYSIWYG preview (exact HTML that gets rendered) · slide/design/caption/quality inspector |
| `#approval` | Rendered slides, caption, sources, resource pack, QC; approve & publish with confirmation; reject with reason |
| `#automation` | Pipeline status, schedule/mode/category config (IST), job history with logs |
| `#dm` | Comment-to-DM campaigns: keyword, linked post, private reply, follow gate, resource pack, dry-run scan, deliveries |
| `#analytics` | Real Graph API insights only (reach, followers, interactions, per-post, category, format) |
| `#settings` | Meta diagnostics + token renewal, visual identity, defaults, engines and cost controls |

## Architecture

```
src/
  config.py              paths, IST, categories (CMS_DB_PATH / CMS_OUTPUT_DIR override for tests)
  store.py               SQLite helpers, settings, events, background job runner (jobs table)
  workflow.py            topic → draft → render → QC → submit → publish (PUBLISHED only on a Meta media id)
  research/harvester.py  GitHub Search, HN Algolia, Hugging Face → dedupe → fetch & verify source → score
  generator/creative.py  slide content from verified fields + README install commands; HTML templates; headless render
  qc/evaluator.py        10 checks on the real slides/caption/source
  scheduler/daily_runner.py  in-process IST scheduler (research_time, target_publish_time; 30-min grace)
  automation/comment_responder.py  campaign scan: one private reply per comment, follow gate via DM reply + profile lookup
  meta_graph_client.py   Graph API v22: publish (carousel/single), diagnostics, insights, permalink
  dashboard/app.py       FastAPI JSON API + static frontend
  dashboard/static/      build-free ES modules, vendored three.js r170 + lucide 0.460
```

Storage: existing `data/content_store.db` (migrated in place, idempotently). Rendered posts: `output/carousels/<id>/slide_NN.jpg`.
A copy of the pre-redesign DB and app is in `backup_pre_redesign/`.

## Safety defaults

* Review Mode is the default; Auto Mode needs an explicit confirmation (UI dialog + `confirm_auto` server check).
* Publishing needs `{"confirm": true}`, a fresh render, a verified source and a valid token for the configured `INSTAGRAM_ACCOUNT_ID`. A new token is saved only if it can read that exact account.
* Comment-to-DM sends private replies only (public replies opt-in per campaign), never messages a comment twice, and live scans require an active campaign + confirmation. Dry-run preview sends nothing.
* Secrets stay in `.env`; no API returns token values.

Docs: `DESIGN_AUDIT.md`, `IMPLEMENTATION_PLAN.md`, `FEATURE_STATUS.md`, screenshots in `docs/screenshots/`.

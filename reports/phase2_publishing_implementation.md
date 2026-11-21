# Phase 2: Manual Publishing Reliability (Implementation)

Status: **implemented locally, not committed, not deployed.** Branch `feat/publishing-reliability`, created from `main` @ `1ed4af5`.
No production data touched. No real Instagram call was made (tests use a fake Graph API, and the UI check ran on a database copy with no token).

## 1. Git state and preservation

| Item | Detail |
|---|---|
| Starting point | `main` @ `1ed4af5`, clean except the changes below |
| Uncommitted changes found before Phase 2 (all from earlier in this session) | `src/dashboard/app.py` (`/api/cron/tick`), `tests/test_app.py` (tick test), `vercel.json` (two fixed crons removed), `reports/instagram_automation_audit.md` |
| How they were preserved | Carried onto the new branch unchanged. Their diff is saved at `backups/pre_phase2_20261121/uncommitted_before_phase2.diff` |
| Backups | `backups/pre_phase2_20261121/` holds copies of every file Phase 2 changed (git-ignored, local only) |
| Conflicts | None. Phase 2 added to `app.py` next to the tick change without touching it |

**Note:** with the timing changes, `vercel.json` currently has **no crons**, and nothing calls `/api/cron/tick` yet. That gets wired up with QStash in Phase 5. Don't deploy this branch on its own without deciding what triggers research and the pipeline.

## 2. What changed

### `src/meta_graph_client.py`
* New `request()`: every Graph call returns `{ok, data}` or `{ok: False, error}`. The error keeps **HTTP status, code, subcode, type, message, fbtrace_id**, plus `kind` (meta / timeout / network / processing / processing_timeout / config), an `uncertain` flag (timeouts, network errors, 5xx: the request *may* have taken effect), and an actionable `hint`.
* `format_error()` turns it into one dashboard line: `message → what to do [code · subcode · HTTP · fbtrace]`.
* Hints cover: expired or invalid token (190), missing permission (10, 200-299), rate or publishing limits (4/17/32/613, 2207042), image download failure (9004, 2207052…), unsupported format, aspect ratio, timeouts and processing delays.
* `_scrub()` strips `access_token=` / `client_secret=` from any text before it reaches an error, a log or the DB. `requests` puts the URL, with the token, into connection error messages.
* Step methods: `create_container`, `create_carousel_container`, `container_status`, `wait_container` (polls IN_PROGRESS → FINISHED, 120 s limit, 3 s interval; ERROR/EXPIRED fail; network blips are retried), `publish_creation`, `find_published_media` (locates a post whose media id was lost), `token_scopes`.
* `check_image_url()`: requires `https://`, HTTP 200 (HEAD, falling back to GET when HEAD is refused) and `image/jpeg`.
* Old `publish_carousel`, `publish_single_image`, `publish_container` and `wait_for_container_ready` are kept as wrappers (used by `mcp_server.py` and `publish_live_carousel.py`). They now poll the children too and return Meta's real error.

### `src/workflow.py`: `publish()` rewritten, plus `recover_stuck_publishing()`
Lifecycle (column `carousels.publish_stage`): **VALIDATING → UPLOADING → PROCESSING → PUBLISHING → PUBLISHED**. Any failure sets status **`PUBLISH_FAILED`** and keeps the stage where it failed.

1. **Atomic claim**: `UPDATE carousels SET status='PUBLISHING' … WHERE id=? AND status IN ('PENDING_APPROVAL','PUBLISH_FAILED')`. Exactly one request gets `rowcount = 1`. Every other click, tab or serverless instance gets "already being published". This is a DB-level guard, not a Python lock. `publish_attempt_at` (UTC) is recorded.
2. **VALIDATING**: account check, token permission check (`instagram_content_publish`, when Meta exposes the scopes), **reconciling any earlier attempt** (see 5), then every slide URL is checked for public HTTPS + 200 + JPEG.
3. **UPLOADING**: one container per image. Child ids are saved as they're created (`ig_children_json`). A single image saves its container straight away.
4. **PROCESSING**: every child must be FINISHED. Then the parent is created and **its id saved before it's polled** (`ig_container_id`), and polled until FINISHED.
5. **PUBLISHING**: `media_publish` is sent only once the saved parent is FINISHED.
   * Success → `PUBLISHED` with media id and permalink (the only code path that writes PUBLISHED, `_mark_published`).
   * Definite Meta error → `PUBLISH_FAILED` with the full error.
   * **Uncertain (timeout, network, 5xx)** → the container status is checked straight away: `PUBLISHED` → marked published (media id found by caption + time); `FINISHED/ERROR/EXPIRED` → `PUBLISH_FAILED` with "Meta confirms NOT published, safe to retry"; still unknown → left in `PUBLISHING` with a note. **It never re-sends `media_publish` blindly.**
6. **Retry safety**: before any new attempt on a post that has an earlier container, Meta is asked whether that container is `PUBLISHED`. If it is, the post is marked published and nothing is posted again. If Meta can't be reached, the retry is refused instead of risking a duplicate.

`recover_stuck_publishing()`: for posts in `PUBLISHING` for more than 10 minutes (longer than Vercel's 300 s limit, so the request is certainly dead):
* has `ig_media_id` → PUBLISHED, with no Meta call
* no container saved → `media_publish` was never sent → `PUBLISH_FAILED`, safe to retry
* container `PUBLISHED` → PUBLISHED
* container FINISHED/ERROR/EXPIRED/gone → `PUBLISH_FAILED`, safe to retry
* Meta unreachable → left untouched, error reported
* legacy row with no attempt timestamp (from before container tracking) → recent media searched by caption before deciding

It runs from the **Check status** button, when Publish is clicked on a `PUBLISHING` post, and on every scheduler tick.

### `src/store.py`
* `update()` returns rows affected (used by the atomic claim; works on SQLite and Postgres).
* `utc_now()` gives UTC ISO-8601 for new timestamp fields.
* `recover_stale_jobs(older_than_minutes)` fails only `RUNNING` jobs older than N minutes, which is safe on Vercel. The no-argument local startup behaviour is unchanged.

### `src/db/migrate_v2.py` (additive only)
New `carousels` columns, on SQLite through `_add_cols` and on Postgres through `ALTER TABLE … ADD COLUMN IF NOT EXISTS`:
`ig_container_id`, `ig_children_json`, `publish_stage`, `publish_attempt_at` (**UTC**), `publish_error_json`. No existing column or value changes, and historic IST timestamps are untouched.

### `src/dashboard/app.py`
* `POST /api/carousels/{id}/publish` also accepts `PUBLISHING` posts (`publish()` reconciles or refuses) and clears jobs orphaned for over 15 minutes.
* New `POST /api/carousels/{id}/reconcile` ("Check status"). It asks Meta and **never publishes**.

### `src/scheduler/daily_runner.py`
`tick()` first does housekeeping: stale jobs, then stuck posts.

### `src/dashboard/static/js/pages/approval.js` (same design, small additions)
* Failed notice: "failed during <stage>" plus the full actionable Meta error.
* `PUBLISHING` with no running job: warning plus **Check status** button.
* The button reads **Retry publish** on failed posts.
* The Creator page publish step already shows the job stage and the error text, which now includes the stage names and the Meta details. No change needed.

### Design decision: status vs stage
`carousels.status` keeps its existing values (`PUBLISHING` covers any publish in progress), because the editing locks, tabs and filters across the UI already rely on them. The six lifecycle steps live in the new `publish_stage` column. This keeps every existing screen working.

## 3. Not changed
* `api/index.py`: no change needed (entry point only).
* `api/render.js` and Vercel Blob: slide URLs are already public HTTPS JPEGs, and `check_image_url` now proves it before Meta is called.

## 4. Known limitations
* **Postgres migration not run against a Postgres server** here (no local Postgres). The SQL is standard (`ADD COLUMN IF NOT EXISTS`, PG ≥ 9.6) and runs inside the existing advisory-locked migration. Run it on a Neon branch or staging copy first (deployment checklist, Phase 10).
* A media id that's lost after an uncertain publish is recovered by matching **caption + time** against the last 10 posts. If you publish over 10 posts in between, or edit the caption on Instagram, the post is still marked PUBLISHED (Meta confirmed it) but without a media id, so no auto DM campaign is created for it. A log entry says so.
* `token_scopes()` needs `debug_token`. If Meta doesn't return scopes, the permission pre-check is skipped and Meta's own error (now visible) covers it.
* The publish job still runs inline in the request on Vercel (300 s limit). The worst case is about 120 s per container wait. Splitting the scheduled pipeline into separate jobs is Phase 5.
* The in-memory per-kind job lock in `start_job` is unchanged. Publishing no longer relies on it (the DB claim is the guard). Replacing it for the other job kinds is Phase 5/8.

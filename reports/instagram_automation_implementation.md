# Instagram Automation: Implementation Summary (Phases 2–9)

Branch **`feat/publishing-reliability`** (from `main` @ `1ed4af5`). **Not committed, not deployed, no production migration, no real publish or DM.**
Tests: **140 passed, 0 failed, 0 skipped**, with all real network access blocked in tests.

Per-phase detail: `phase2_publishing_implementation.md`, `phase3_webhooks_implementation.md`, `phase4_comment_to_dm.md`, `phase5_scheduler.md`, `phase6_dashboard.md`, `meta_configuration_checklist.md`.

## 1. Root cause of the manual publishing failure
The exact Meta error from production was **not retrieved** (production logs and DB need your login; you chose to investigate later). The code audit found the confirmed reasons it failed **invisibly** and could get stuck:
1. **Meta's error was thrown away**: container failures returned `None` and the UI showed a generic message. *(fixed: code, subcode, message, fbtrace, HTTP status and an actionable hint are now shown)*
2. **Posts could stay in "Publishing" for good** after a function timeout or crash, and the Publish button then refused them. *(fixed: reconciled with Meta, plus Check status)*
3. **The scheduled run tried research + build + render + publish in one 300 s function**, a likely cause of "build created, nothing published". *(fixed: separate jobs)*
4. **No duplicate protection** (in-memory lock per instance, no container tracking). *(fixed: atomic DB claim, saved container ids, reconcile before retry)*

The Meta audit also found the token **lacks `pages_manage_metadata`** and is a **User** token (fine for publishing, not for DMs). Once deployed, the next publish attempt will show Meta's real reason on screen.

## 2. Architecture now
```
Meta webhook ──signed──▶ /api/webhooks/instagram ─▶ webhook_events (unique) ─▶ QStash ─signed─▶ /api/queue/webhook-event
                                                                                   └▶ dm_engine: verify comment → match → claim → 1 private reply
QStash schedules (CRON_TZ=Asia/Kolkata, from dashboard times) ─signed─▶ /api/queue/job/{research|generate|publish_due|analytics|tick}
   research · generate (never publishes) · publish_due (approved + due only) · analytics · maintenance (every 10 min)
Dashboard ─▶ /api/automation/overview (DB-backed statuses) · Run now (same DB lease) · Webhook health · Check Meta configuration
```

## 3. Existing uncommitted changes, preserved
Found before Phase 2 (all from earlier in this session): the `/api/cron/tick` endpoint, the two fixed crons removed from `vercel.json`, a tick test, and the audit report. They were carried onto the branch unchanged, and their diff is saved in `backups/pre_phase2_20261121/uncommitted_before_phase2.diff`. Phase 5 then built on them (the tick runs split jobs; `vercel.json` now has one maintenance-only cron).

## 4. Exact files changed
**Modified (14):** `.gitignore` (+`backups/`), `vercel.json`, `src/meta_graph_client.py`, `src/workflow.py`, `src/store.py`, `src/db/migrate_v2.py`, `src/dashboard/app.py`, `src/automation/comment_responder.py`, `src/scheduler/daily_runner.py`, `src/dashboard/static/js/pages/{approval,automation,dm}.js`, `src/dashboard/static/js/ui.js`, `tests/test_app.py`.
**New source (6):** `src/qstash_client.py`, `src/automation/webhook_inbox.py`, `src/automation/dm_engine.py`, `src/scheduler/jobs.py`, `src/scheduler/qstash_schedules.py`, `src/meta_audit.py`.
**New tests (8):** `tests/conftest.py` (blocks real network), `test_publishing.py`, `test_webhooks.py`, `test_dm_engine.py`, `test_scheduler.py`, `test_dashboard.py`, `test_meta_audit.py`, `test_security.py`.
**Not changed:** `api/index.py`, `api/render.js`, `requirements.txt`, `package.json`, the generators and research code.

`tests/test_app.py`: 4 existing tests were **adapted, none removed**. Their stubs moved to the new internal calls, and their assertions are kept or strengthened (publish success, webhook wake, scheduler window, cron tick).

## 5. New dependencies
**None.** QStash is called over its REST API with `requests`; JWT verification uses the standard library.

## 6. Database migrations (additive only; run automatically by the app's existing `migrate()` on startup)
| Change | Purpose |
|---|---|
| `carousels` + `ig_container_id`, `ig_children_json`, `publish_stage`, `publish_attempt_at` (UTC), `publish_error_json`, `approved_at` (UTC); `scheduled_for` (previously unused) now holds UTC | Publish tracking, reconciliation, scheduling |
| `campaigns` + `keywords`, `guide_url` | Multiple keywords, guide link |
| `dm_deliveries` + `event_id`, `sent_at` (UTC), `retryable`, `last_error_json` | Delivery state and retries |
| `jobs` + `slot_key` | One success per daily slot |
| **New** `webhook_events` (unique `event_key`, unique `comment_id`), `dm_delivery_log`, `job_locks` | Durable inbox, history, cross-instance lease |
| settings defaults `generate_time` (""), `analytics_time` ("23:30") | New dashboard fields |

Checked on a **copy of the local database**, migrated twice: no table or column removed, every existing row and value unchanged, idempotent. Postgres DDL uses only `CREATE … IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` and was reviewed statement by statement, but **it hasn't been executed on a real Postgres** (no Postgres available locally). See the deployment checklist step 2.

## 7. QStash configuration and cost
* Verified on Upstash's pricing page (2026-11-21): **free plan $0, 1,000 messages/day (each attempt counts), 10 schedules.**
* Usage: **5 schedules**; about **148 messages/day** from schedules (4 daily + 144 ticks), plus 1 per comment event, plus retries only on failure. That leaves roughly 850/day for comments.
* Over the limit, QStash returns 429 for free accounts; events stay `PENDING` and the sweep handles them. **No automatic charges; no paid plan enabled.** Vercel stays on Hobby (one daily maintenance cron).

## 8. Required Vercel environment variables
| Variable | Status | Purpose |
|---|---|---|
| `META_APP_SECRET` | **add** | Webhook signature check (webhooks are rejected without it) |
| `META_PAGE_ACCESS_TOKEN` | **add** | Private replies and DMs (the current token is a User token) |
| `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY` | **add** | Queue, schedules, callback verification |
| `QSTASH_URL` | optional | Regional endpoint (default `https://qstash.upstash.io`) |
| `APP_URL` | **set exactly** `https://insta-post-automation-pi.vercel.app` | Callback URLs QStash signs |
| `CRON_SECRET` | keep / add | Daily maintenance cron and `/api/cron/*` |
| `META_ACCESS_TOKEN` (new one with `pages_manage_metadata`), `INSTAGRAM_ACCOUNT_ID`, `META_APP_ID`, `DATABASE_URL`, `APP_PASSWORD`, `APP_SECRET`, Blob token | existing | unchanged |

## 9. Required Meta configuration
See `meta_configuration_checklist.md`: app mode (Live for real followers), Advanced Access, app secret, Instagram webhook fields `comments` + `messages`, new token with `pages_manage_metadata`, Page access token, Page→app subscription (**needs your approval: it changes Meta config**).

## 10. Known limitations
* **Postgres migration not executed here** (it will run on the first production request; test it on a database branch first).
* Production publish error not yet seen. The new error reporting will show it on the first attempt.
* A lost media id after an uncertain publish is recovered by caption + time over the last 10 posts. If not found, the post is still marked Published (Meta confirmed it) but gets no auto DM campaign.
* The same person posting two keyword comments at the same instant can get two private replies (one per comment, which Meta allows).
* `UNCERTAIN` private replies need a human decision; Meta has no "was it delivered" API.
* Custom per-post times have 10-minute resolution (free-plan budget). Daily jobs are exact to the minute.
* App mode and Advanced Access can't be read through the API. They're dashboard-only checks.
* QStash schedule upsert with a changed destination is documented but hasn't been tried live. Check the QStash console after the first sync.
* The manual "Run full pipeline" button still runs the old combined flow (kept for convenience; the scheduler doesn't use it).

## 11. Deployment and rollback
See **`instagram_automation_deployment_checklist.md`**.

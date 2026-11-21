# Instagram Automation Audit

Date: 2026-11-21 · Repo at `1ed4af5`, plus uncommitted changes (see §8) · Scope: Phase 1 only. **Nothing deployed or changed in production.**

## 0. How this was audited

* Read every source file that is involved: `src/meta_graph_client.py`, `src/workflow.py`, `src/media.py`, `api/render.js`, `api/index.py`, `src/store.py`, `src/db/migrate_v2.py`, `src/dashboard/app.py`, `src/automation/comment_responder.py`, `src/scheduler/daily_runner.py`, `vercel.json` and the frontend pages `create.js`, `approval.js` and `automation.js`.
* **Not yet checked: the live production job log for the failed manual publish.** The production API needs the dashboard login (`/api/carousels/1` returns 401), and the production Postgres database isn't reachable from this machine. So the *exact* Meta error behind the publish failure is **not confirmed**. §2 lists what the code guarantees and what it makes likely. One look at the failed publish job's log turns this into a confirmed cause (see §9).

## 1. Stack

| Area | What it is |
|---|---|
| Backend | FastAPI (Python), served on Vercel by `api/index.py` (`maxDuration` 300 s) |
| Renderer | Node function `api/render.js`: serverless Chromium → JPG → **Vercel Blob** (public HTTPS URLs) |
| DB | Vercel Postgres in production (`DATABASE_URL`), SQLite locally. One SQL dialect, translated by `store.to_pg` |
| Instagram API | Graph API **v22.0** on `graph.facebook.com`, i.e. Instagram via **Facebook Login** (Page-linked professional account), not "Instagram Login" |
| Auth | Long-lived token from `META_ACCESS_TOKEN` env, or one renewed in Settings and saved in the `secrets` table. Account id comes from env `INSTAGRAM_ACCOUNT_ID` |
| Jobs | `store.start_job`: one row in `jobs`, per-kind lock held **in memory**. On Vercel the job runs inline inside the HTTP request |
| Scheduler | Local: an in-process thread (`daily_runner.tick`). Vercel: two fixed crons in `vercel.json` (17:30 and 19:00 IST) that ignore the dashboard times |
| Webhooks | `GET/POST /api/webhooks/instagram` already exist (`app.py:701-756`) |

## 2. Manual publishing: confirmed issues

Flow: Publish button (`create.js:176` / `approval.js:127`) → `POST /api/carousels/{id}/publish` (`app.py:408`) → `start_job("publish")` runs inline → `workflow.publish` (`workflow.py:260`) → `MetaGraphClient.publish_carousel` / `publish_single_image`.

| # | Confirmed issue | Where | Effect |
|---|---|---|---|
| P1 | **Meta's error is thrown away.** If creating a child or parent container fails, the function returns `None` and only `logger.error`s the response. The UI then shows a generic "Failed staging slide N" or "Failed creating parent carousel container". | `meta_graph_client.py:119-154, 207, 214` | You never see the real code, subcode or message (token expired, missing permission, image rejected, rate limited). **This is why the failure isn't actionable today.** |
| P2 | **A post can get stuck in `PUBLISHING` for good.** Status is set to `PUBLISHING` before Meta is called. If the Vercel function dies (300 s limit, cold-start crash, network timeout), nothing resets it. `recover_stale_jobs` runs only on non-Vercel startup. The publish endpoint then refuses anything that isn't `PENDING_APPROVAL` or `PUBLISH_FAILED`. | `workflow.py:286`, `app.py:147-150, 414-415`, `store.py:201` | The post can't be published or retried from the UI, and the job shows "running" forever. |
| P3 | **Duplicate-post risk.** No container id or "publish attempted" marker is saved. If `media_publish` succeeds but the response is lost (20 s timeout), the post is marked `PUBLISH_FAILED`. Retrying builds new containers and publishes **a second copy**. | `meta_graph_client.py:177-192`, `workflow.py:274-301` | Duplicate posts on @sonu.ai.lab |
| P4 | **The concurrency lock doesn't work on Vercel.** `_running` is a Python dict in one process, and each Vercel instance has its own. Two clicks or tabs landing on different instances both publish. | `store.py:162-175` | Duplicate publish and duplicate pipeline runs |
| P5 | **Child containers are never status-checked.** Only the parent is polled, and only for 15 × 3 s = 45 s. A slow parent is reported as "timed out", even though it may finish and could still be published. | `meta_graph_client.py:156-175, 201-219` | False failures, and retries that risk P3 |
| P6 | **Single-image `PUBLISH_FAILED` text drops the error structure.** `resp.text[:300]` is raw JSON, not code, subcode and message. | `meta_graph_client.py:279-290` | Same as P1, smaller |
| P7 | **Image URLs aren't pre-checked.** Vercel Blob URLs are public HTTPS, which is correct, but there's no HEAD check for 200 + `image/jpeg` before Meta fetches them. A deleted or expired blob shows up later as an opaque container error. | `workflow.py:288-294`, `media.py:50-55` | Opaque failure |

**Suspected (needs the live log):**
* **S-P1. Token type or permission.** `diagnostics()` already reports `instagram_content_publish`. If it's missing, or the token expired (`code 190`), every publish fails at the container step and P1 hides it.
* **S-P2. Scheduled "build but no publish".** `run_pipeline` does research (if not done today), generate, render (Chromium ~20-60 s), QC **and** publish, all in **one** 300 s function (`workflow.py:344-372`). Running out of time partway through leaves a built post and (P2) a stuck job. Also possible: QC below 85 → `DRAFT`, Review mode → `PENDING_APPROVAL`, or the daily limit.

## 3. Comment-to-DM and webhooks: confirmed issues

What exists: verify endpoint (verify token stored in `secrets`), POST handler that checks `X-Hub-Signature-256`, matches on media id, then **re-reads comments from the Graph API** (good: a forged event can't make it DM a stranger). Then: private reply with a quick-reply button → follow gate → guide text + images (`comment_responder.py`).

| # | Confirmed issue | Where | Effect |
|---|---|---|---|
| W1 | **Unsigned webhooks are accepted when `META_APP_SECRET` is unset.** The signature check is skipped entirely. | `app.py:716-722` | Anyone can trigger scans (low impact thanks to the re-read, but it's still a hole) |
| W2 | **Events can be dropped.** A 3-second throttle per campaign, per instance, skips the scan, and nothing re-scans later. Two comments within 3 s: the second can be left unanswered until another comment arrives. | `app.py:709, 741-743` | Missed DMs during comment bursts |
| W3 | **Duplicate DM race.** The private reply is **sent first** and recorded after (`INSERT OR IGNORE`). Meta retries, or two concurrent instances, can both send before either inserts. | `comment_responder.py:142-149` | Same person gets the opener twice |
| W4 | **No event store.** Incoming webhooks aren't saved, so there's no "last event received" and no proof Meta is delivering. | — | No webhook health data |
| W5 | **Processing happens inside the webhook request.** Graph calls run before the 200 goes back. Meta expects a fast 200 and retries or disables slow endpoints. | `app.py:739-750` | Retries feed W3; risk the subscription is disabled |
| W6 | **One keyword per campaign.** No multiple keywords or aliases. Matching is case-insensitive and whole-word, which is fine for "AGENT" / "agent". | `comment_responder.py:120`, schema `campaigns.keyword` | Phase 4 needs a change |
| W7 | **Only the newest ~50 comments are read**, with no paging. | `comment_responder.py:70` | Older keyword comments on busy posts are missed |
| W8 | **No delivery retry.** `FAILED` rows are final, with no "retry if safe" logic or UI. | `comment_responder.py:144, 180` | — |

**Suspected:**
* **S-W1. Wrong token for messaging.** DMs go to `me/messages`. With Facebook-Login Instagram messaging, that only works with a **Page** access token (or as `/{page-id}/messages`). If `META_ACCESS_TOKEN` is a *user* token, private replies fail. Settings → diagnostics `token.type` shows which it is.
* **S-W2. Meta app setup.** Webhooks for comments by people with no role on the app arrive only when the app is **Live** with **Advanced Access** to `instagram_manage_comments` (and `instagram_manage_messages` for DMs). If the app is in Development mode, only your own test accounts trigger events. That would look exactly like "the webhook doesn't work".

## 4. Scheduler: confirmed issues

| # | Issue | Where |
|---|---|---|
| S1 | The dashboard Research and Publishing times are **ignored on Vercel**. The crons are hard-coded at 17:30 and 19:00 IST. | `vercel.json` (committed version) |
| S2 | Research, generation, render, QC and publish all run in **one job**, which inherits the 300 s limit and P2. | `workflow.py:344-372` |
| S3 | A slot is marked done **before** its job runs, so a failed run isn't retried that day. | `daily_runner.py:57-62` |
| S4 | `carousels.scheduled_for` exists but nothing uses it. There are no per-post scheduled times. | schema |
| S5 | All timestamps are stored as **IST wall-clock text**, not UTC. | `store.ts()`, `migrate_v2.py` (`ts_ist` shift) |
| S6 | Vercel Hobby crons run **once a day at most**, and Vercel may fire each one at any minute within its hour. | Vercel limits |

## 5. Security

* Meta token is stored **in plaintext** in `secrets` (or env). It's never returned by `/api/settings`. Good, but it isn't encrypted at rest.
* Login uses an HMAC-signed session cookie. Cron endpoints need `CRON_SECRET`. Renderer is guarded by a key derived from `APP_SECRET`. All good.
* Job logs contain slide URLs and usernames, not tokens. Good.
* W1 (optional signature check) is the one real gap.

## 6. Database changes required (minimum, additive only; no data deleted)

| Change | Why |
|---|---|
| `carousels`: add `ig_container_id`, `publish_attempt_at` (UTC), and use the existing `scheduled_for` as **`scheduled_at` UTC** | Idempotent publish and duplicate guard (P3), recovering stuck posts (P2), per-post scheduling (S4) |
| New `webhook_events` (id, received_at UTC, object, field, media_id, comment_id, commenter_id, text, raw_json, signature_ok, processed_at, result) with **unique** `comment_id` | Event store, dedup, Webhook Health (W3, W4) |
| `campaigns`: add `keywords` (comma list; existing `keyword` stays as the first entry) | Multiple keywords (W6) |
| `dm_deliveries`: add status `SENDING`, claimed **before** sending (unique `comment_id` already exists) | Atomic claim stops duplicate DMs (W3) |
| `jobs`: add `lease_until` (UTC) and a unique "one RUNNING per kind" guard through Postgres advisory lock or row update | Real cross-instance locking (P4), detecting stale jobs (P2) |
| New `schedules` rows in `settings` (`research_time`, `target_publish_time` already exist) plus `last_*_ok` | S1, S3 |

Proposal for S5: **new** columns are UTC. Existing IST columns stay as they are and are documented, and the UI converts. Rewriting every historic timestamp to UTC is riskier than it's worth. **Your call (see §9).**

## 7. Meta permissions and dashboard setup (manual; code can't do these)

* Permissions with **Advanced Access**, app **Live**: `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, plus `business_management` if the Page is in a Business portfolio.
* App Dashboard → Webhooks → **Instagram** object: callback `https://insta-post-automation-pi.vercel.app/api/webhooks/instagram`, the verify token shown in Settings, subscribe fields **`comments`** and **`messages`** (`messaging_postbacks` optional).
* Subscribe the Facebook Page to the app: `POST /{page-id}/subscribed_apps?subscribed_fields=feed` using the Page token. The app can do this itself once a Page token is available; I'll add a button.
* Vercel env: `META_APP_SECRET` (required for signatures), `CRON_SECRET`, and a Page access token for messaging (or derive it from the user token through `/me/accounts`).

## 8. Uncommitted work in the tree right now

From the timing fix started earlier (not deployed): `GET /api/cron/tick` (runs research or pipeline when the dashboard times are due), the two fixed crons removed from `vercel.json`, and one test. **Nothing triggers `tick` yet.** If this were deployed as it stands, there'd be *no* scheduled runs. It gets finished in Phase 6.

## 9. Recommended implementation plan

Order is by user impact. Each phase gets mocked-Meta tests. Nothing is deployed without your OK.

1. **Phase 2: publish fix** (small, highest value)
   * `MetaGraphClient`: a single `_post` helper that keeps `code`, `subcode`, `message` and `fbtrace_id`. Poll children and parent (configurable, up to ~2 min). Treat `media_publish` timeouts as "unknown", then check `/{ig-user}/media` for the container before retrying.
   * `workflow.publish`: preflight (token valid + `instagram_content_publish` + HEAD every image URL), then claim the post atomically (`UPDATE … SET status='PUBLISHING', publish_attempt_at=now WHERE id=? AND status IN (…)`; 0 rows means it's already in progress). Save `ig_container_id` before publishing. Stages: Validating → Uploading → Processing → Publishing → Published / Failed, with the real Meta error.
   * Recover stuck `PUBLISHING` posts: older than 10 min with no media id → check Meta for the container → mark `PUBLISHED` or `PUBLISH_FAILED`. Runs on every tick and when the post page opens.
2. **Phase 3/4: webhooks + DM engine**
   * Always verify the signature (reject if `META_APP_SECRET` is missing). Store every event in `webhook_events` (dedup on comment id). Remove the 3 s throttle.
   * **Async on Vercel without a paid queue:** reply 200 right after the insert, then process. Python on Vercel can't run code after the response, so the realistic options are (a) process inline but bounded (fast: one comment, one private reply, usually under 2 s), or (b) hand off to QStash (free tier). **Recommendation: (a)**, with the atomic `SENDING` claim. That makes Meta retries harmless.
   * Use the comment from the payload (id, text, from.id, media.id), then confirm it with one Graph `GET /{comment-id}` call (still forgery-proof, and no 50-comment re-read). Support multiple keywords, a per-campaign template and guide URL, and safe retry only for `FAILED` rows whose private reply was never accepted by Meta.
   * Page-token messaging: call `/{page-id}/messages` with the Page token from `/me/accounts`.
3. **Phase 5: split jobs.** `research`, `generate` (create, render, QC, save draft or queue), `publish_due` (approved posts whose `scheduled_at` ≤ now), and `analytics`. Each one stays far under 300 s and is locked by a Postgres advisory lock.
4. **Phase 6: scheduler.** `tick` decides what's due from the dashboard times and `scheduled_at`, and keeps history in `jobs`. Retries failures (max 3, backoff). Recovers stale leases. **Trigger options** (you said Vercel-only earlier):
   * **Vercel Pro ($20/mo):** one `*/5 * * * *` cron → `tick`. Simplest, all-Vercel.
   * **Vercel Hobby (free):** 24 once-a-day crons, one per hour, so runs land within the configured hour, not the minute.
   * **QStash (Upstash, free tier, roughly 1k messages/day; to verify at implementation):** when you save Settings, the app creates exact-minute schedules through the QStash API. That's 2-3 messages a day, with retries built in, and the Vercel app and DB stay as they are. **Recommended if you want exact times on Hobby.**
   * Inngest: generous free tier and has a Python SDK, but needs its own serve endpoint and a bigger integration. Trigger.dev: TypeScript-first, a poor fit for this Python backend.
5. **Phase 7: dashboard.** Automation page gets per-system status cards (last run, next run, status, success/fail counts, latest error, retry, logs) and a Webhook Health card (config, last event, last processed comment, last DM sent, failed count, subscription check through `GET /{page-id}/subscribed_apps`). The Comment-to-DM page shows real `webhook_events`.
6. **Phase 8-10:** additive migrations (§6), the 19 mocked tests requested, and the two remaining reports.

### Decisions needed from you before I start

1. **Scheduler trigger:** Vercel Pro cron, Hobby 24-hourly crons, or QStash (exact times, free)?
2. **UTC:** UTC for new fields only (recommended), or migrate all existing timestamps?
3. **Live publish failure log:** sign in to the dashboard in the Claude browser pane, or paste the Log of the failed publish job, so P1/S-P1 can be confirmed instead of inferred.
4. **Meta app status:** is the Meta app **Live**, with Advanced Access to `instagram_manage_comments` and `instagram_manage_messages`? (Meta App Dashboard → App Review → Permissions and Features.)

# Phase 3: Instagram Webhooks + QStash (Implementation)

Status: **implemented locally on `feat/publishing-reliability`, not committed, not deployed.** No real Meta or QStash call was made.
Test suite: **71 passed** (19 original + 28 Phase 2 + 24 Phase 3), with all real network access blocked.

## 1. QStash: verified facts (2026-11-21)

Checked on Upstash's own pages, not third-party reviews (several reviews still quote an older 500/day figure).

| Item | Fact | Source |
|---|---|---|
| Free plan | **$0, 1,000 messages/day**, 1 MB per message, **10 active schedules**, 10 queues, DLQ and logs kept 3 days, max delay 7 days | [upstash.com/pricing/qstash](https://upstash.com/pricing/qstash) |
| Billing unit | "Each delivery attempt counts as one message", so retries count toward the 1,000 | same |
| Over the limit (free) | Requests can get **HTTP 429** if usage keeps exceeding the limit. No automatic charge | same |
| Paid (not enabled) | Pay as you go: $1 per 100K messages | same |
| Publish API | `POST /v2/publish/{destination-url}`, `Authorization: Bearer <QSTASH_TOKEN>`, `Upstash-Retries` (default 3), `Upstash-Deduplication-Id` (10-minute window) | [publish docs](https://upstash.com/docs/qstash/api-reference/messages/publish-a-message.md) |
| Retries | Default 3, backoff `min(86400, e^(2.5·n))` s → about 12 s, 2.5 min, 30 min | [retry docs](https://upstash.com/docs/qstash/features/retry.md) |
| Callback signature | `Upstash-Signature` JWT, HS256 with the current or next signing key. Claims: `iss=Upstash`, `sub`=destination URL, `exp`, `nbf`, `body`=base64url(SHA-256(raw body)) | [signature docs](https://upstash.com/docs/qstash/howto/signature.md), [security](https://upstash.com/docs/qstash/features/security.md) |
| Schedules (for Phase 5) | `POST /v2/schedules/{destination}` + `Upstash-Cron` (1-minute resolution, `CRON_TZ=` supported), `Upstash-Schedule-Id` upserts, list `GET /v2/schedules`, delete `DELETE /v2/schedules/{id}` | [schedule docs](https://upstash.com/docs/qstash/api-reference/schedules/create-a-schedule.md) |
| Python SDK | Official SDKs exist. **Not used**: publish is one REST call and verification is about 30 lines of standard library, so **no new dependency** | — |

**Budget on the free plan:** 1 message per new webhook event, plus retries only on failure. Phase 5 will add a handful of messages a day (exact-time schedules, not a 5-minute poll). That leaves roughly 900+ events a day. Beyond that, QStash may answer 429: events then stay `PENDING` in the database and the sweep processes them, so **nothing is dropped and nothing is billed**. If your comment volume ever approaches this, that's the point to revisit the plan, and I'd stop and ask first.

## 2. What changed

### New `src/qstash_client.py`
* `publish(path, payload, dedup_id, retries=3, timeout=4s)` over REST. The short timeout is because it runs inside the webhook request.
* `verify(signature, raw_body, url)`: checks HS256 against the **current or next** key (rotation-safe), `alg`, `iss`, **`sub` equals this app's exact callback URL**, `exp`/`nbf` (30 s leeway) and the body hash, padded or unpadded. All comparisons are constant-time.
* `destination(path)` builds the public URL from `APP_URL`, the same value the publisher and verifier use.
* Named `qstash_client`, not `qstash`, so it can never shadow the official package.

### New `src/automation/webhook_inbox.py`: durable inbox
* `parse()`: comment events with id, text, `from.id`/`username`, media id, account id and time. DM events (messages, quick-reply taps, postbacks). **Echoes of our own DMs are ignored.**
* `store()`: `INSERT OR IGNORE` (Postgres: `ON CONFLICT DO NOTHING`). Only new rows are returned, so **a duplicate delivery is never queued twice**.
* `dispatch()`: QStash when configured. Locally without QStash, a background worker. On Vercel without QStash, `PENDING` for the sweep.
* `process_event()`: **atomic claim** (`UPDATE … WHERE status IN ('PENDING','QUEUED','FAILED') OR stale PROCESSING`, max 5 attempts), so redeliveries, retries and sweeps never run it twice at once. Returns **500 only for a retryable failure** (QStash retries), and 200 on the last attempt so QStash stops. Result and error are recorded on the row.
* `sweep()`: re-drives `PENDING` (QStash down, quota or not configured), `QUEUED` never delivered (over 10 min), stale `PROCESSING` (over 5 min) and `FAILED` with attempts left. Re-queues through QStash, or processes inline when QStash isn't set up.
* `retry_failed()`: dashboard retry for an event that used all its attempts.
* Handler: a Phase 3 bridge to the **existing** campaign engine (`scan_campaign`, which re-reads comments from Graph, so forged events can't DM anyone). **Phase 4 replaces it** with per-comment processing and claim-before-send.

### DB (additive): new `webhook_events` table
Columns: `event_key` **UNIQUE**, `comment_id` **UNIQUE**, kind/field/account/media/sender/username/text/event_time/raw_json, `status` (PENDING · QUEUED · PROCESSING · PROCESSED · IGNORED · FAILED), attempts, `received_at`, `queued_at`, `qstash_message_id`, `processing_started_at`, `processed_at` (**all UTC**), `result_json`, `error`. Index on `(status, received_at)`. SQLite and Postgres DDL are both included. Postgres SQL translation is checked (`ON CONFLICT DO NOTHING RETURNING id`).

### `src/dashboard/app.py`
| Endpoint | Behaviour |
|---|---|
| `GET /api/webhooks/instagram` | Unchanged (verify token challenge) |
| `POST /api/webhooks/instagram` | **Requires `META_APP_SECRET`** (503 if missing) and **`X-Hub-Signature-256`** (403 if missing or invalid). Stores, enqueues, returns 200. **No Graph API calls.** **3-second throttle removed.** Records `webhook_last_received_at` |
| `POST /api/queue/webhook-event` *(new)* | QStash callback. 401 unless the signature is valid for this exact URL. Idempotent processing |
| `GET /api/inbox/events`, `POST /api/inbox/sweep`, `POST /api/inbox/events/{id}/retry` *(new, login required)* | Event list, counts and health for the dashboard, a manual sweep and a safe retry. Deliberately **not** under `/api/webhooks/`, which skips login |

### `src/scheduler/daily_runner.py`
The tick housekeeping also runs `webhook_inbox.sweep()`.

## 3. Environment variables (new)
| Variable | Needed for |
|---|---|
| `META_APP_SECRET` | **Required.** Webhooks are rejected without it |
| `QSTASH_TOKEN` | Publishing to QStash |
| `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY` | Verifying QStash callbacks |
| `QSTASH_URL` (optional) | Regional endpoint, for example `https://qstash-eu-central-1.upstash.io`. Defaults to `https://qstash.upstash.io` |
| `APP_URL` | Must be the **exact public production URL**, `https://insta-post-automation-pi.vercel.app`, because QStash signs the callback URL and it's checked |

## 4. Known limitations / open points
* **Duplicate DMs are not fully solved until Phase 4.** The inbox guarantees each event is processed once, but the existing engine still sends a private reply before recording it. Two *different* events for the same post (for example two comments arriving together) both trigger a scan, and two concurrent scans could reply to the same comment. Phase 4's claim-before-send (`dm_deliveries` row inserted first, `UNIQUE(comment_id)`) closes this.
* **Postgres not run live.** DDL and the SQL translation are checked, but the table hasn't been created on a real Postgres. Do that on a staging copy first.
* **Meta-side setup still needed**, and I can't confirm it from here: subscribing the `comments` and `messages` fields, the Page subscription and app mode. That's the Phase 7 audit and checklist.
* `/api/queue/` was added to the public prefixes. It's protected by the QStash signature, and an unsigned call gets 401 (tested).

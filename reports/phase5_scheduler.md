# Phase 5: QStash Scheduler and Independent Jobs

Status: **implemented locally on `feat/publishing-reliability`, not committed, not deployed. No QStash schedules were created.**
Tests: **121 passed** (19 original + 28 P2 + 24 P3 + 26 P4 + 24 P5), with all real network access blocked.

## 1. Architecture

| Job | Trigger in production | What it does | Never does |
|---|---|---|---|
| `research` | QStash `sal-research`, daily at **Research time** | Harvests and verifies topics | Generate or publish |
| `generate` | QStash `sal-generate`, daily at **Generate time** (default: 45 min before Publishing time) | One post from the best verified topic → render → QC → Review: waits for approval · Auto: **approved and scheduled** for the next Publishing time | Publish |
| `publish_due` | QStash `sal-publish` at **Publishing time**, plus every tick | Publishes **one** approved post whose `scheduled_for` has passed (through Phase 2's safe `publish()`) | Publish unapproved or legacy rows |
| `analytics` | QStash `sal-analytics`, daily at **Analytics time** (default 23:30) | Read-only metrics into `post_insights` | — |
| `maintenance` | QStash `sal-tick` every 10 min, plus a daily Vercel safety-net cron | Closes orphaned jobs, reconciles posts stuck in Publishing, re-drives undelivered webhook events. Every step runs even if another fails | Create content |
| `process_comment_event` | **Each Meta webhook** (Phase 3/4) | Comment-to-DM | Wait for any schedule |

The old single `run_pipeline` (research + generate + publish in one 300 s function) is **no longer scheduled**. It's kept only for the existing manual "build now" button.

## 2. Requirements → implementation

| # | Requirement | How |
|---|---|---|
| 1 | Asia/Kolkata default | Schedules use `CRON_TZ=<settings.timezone>` (default Asia/Kolkata). Dashboard inputs are IST |
| 2 | New timestamps UTC | `carousels.approved_at`, `carousels.scheduled_for` (new meaning), `job_locks.lease_until`, plus all Phase 2-4 fields |
| 3/4 | Preserve historical IST, no mass conversion | `jobs.started_at/finished_at` and the other older columns keep IST. Nothing was rewritten |
| 5/6 | Research and publishing scheduled independently | Separate QStash schedules and job endpoints |
| 7 | Per-post `scheduled_at` | New "Publish at (IST)" + **Approve & schedule** on the approval page → `POST /api/carousels/{id}/schedule` (IST → UTC, now…+60 days, confirm required). "Clear schedule" removes it. Picked up within 10 min by the tick |
| 8 | Update from dashboard | Saving any time, the pause switch or the timezone in Settings **re-syncs QStash automatically**. There's also `POST /api/scheduler/sync` |
| 9 | Cancel/replace obsolete schedules safely | Fixed ids (`sal-*`) **upserted** (`Upstash-Schedule-Id`) first, then only obsolete `sal-*` schedules deleted. Nothing outside the prefix is touched. Pausing deletes our 5 |
| 10 | No duplicate scheduled jobs | Upsert by id (no duplicate schedules), **`jobs.slot_key`** (one success per daily slot), **`job_locks` lease in the DB** (one run of a kind at a time across instances; an expired lease is taken over) |
| 11 | Bounded exponential backoff | QStash: failed run → HTTP 500 → 3 retries at about 12 s / 2.5 min / 30 min. Local or fallback tick: 2 → 4 → 8 min, max 3 failures per slot |
| 12 | Execution history | Every run is a `jobs` row (kind, trigger, slot, status, stage, log, result, error) |
| 13 | Recover failed or stuck jobs | `maintenance` every 10 min: stale RUNNING jobs closed, stuck posts reconciled against Meta, webhook sweep |
| — | Comment processing stays webhook-triggered | Unchanged from Phase 3/4 |

## 3. QStash usage (free plan, verified 2026-11-21: 1,000 msgs/day, 10 schedules)

| Schedule | Cron | Messages/day |
|---|---|---|
| sal-research | `CRON_TZ=Asia/Kolkata 35 9 * * *` (from Research time) | 1 |
| sal-generate | from Generate time | 1 |
| sal-publish | from Publishing time | 1 |
| sal-analytics | from Analytics time | 1 |
| sal-tick | `*/10 * * * *` | 144 |
| **Total** | **5 of 10 schedules** | **≈148/day** (+ retries only on failure) |

That leaves about 850/day for comment events. **No paid plan is needed or enabled.**

**Precision:** the four daily jobs fire at the exact minute. Posts given a custom time go out within ≤10 min (tick resolution). The daily auto post goes out exactly at Publishing time.

## 4. Files

| File | Change |
|---|---|
| `src/scheduler/jobs.py` *(new)* | Job registry, DB lease lock, slot dedup, `run()`, local backoff, `next_runs()`, `run_maintenance` |
| `src/scheduler/qstash_schedules.py` *(new)* | Desired schedules from settings, safe `sync()` |
| `src/qstash_client.py` | `upsert_schedule`, `list_schedules`, `delete_schedule` |
| `src/workflow.py` | `run_generate`, `run_publish_due`, `run_analytics`, `schedule_times`, `ist_to_utc`/`utc_to_ist`, `next_publish_utc`, `schedule_post`/`unschedule_post`, `due_post` |
| `src/scheduler/daily_runner.py` | `tick()` now runs the split jobs (local thread and fallback). The old `SLOTS`/pipeline slot is removed. `next_runs()` delegates |
| `src/store.py` | `start_job(..., slot_key=)` |
| `src/db/migrate_v2.py` | Additive: `jobs.slot_key`, `carousels.approved_at`, `job_locks` table; settings defaults `generate_time` (""), `analytics_time` ("23:30") |
| `src/dashboard/app.py` | `POST /api/queue/job/{kind}` (QStash-signed, plus `tick`); `GET /api/scheduler/status`; `POST /api/scheduler/sync`; `POST/DELETE /api/carousels/{id}/schedule`; settings validators and auto re-sync; `/api/cron/maintenance` |
| `vercel.json` | One daily **maintenance-only** cron (`30 21 * * *` UTC = 03:00 IST) as a safety net, within Hobby's once-a-day limit. It never creates or publishes content |
| `src/dashboard/static/js/pages/approval.js` | "Publish at (IST)" + Approve & schedule, scheduled notice + Clear schedule |
| `tests/test_scheduler.py` *(new)* | 24 tests |
| `tests/test_app.py` | `test_scheduler_fires_once_inside_window` updated to the split jobs. Same window assertions, plus "generate window missed" |

## 5. Tests (all PASS)

| Category | Tests |
|---|---|
| Exact scheduled time | `test_schedules_built_from_dashboard_times` (exact CRON_TZ crons), `test_publish_due_exact_time` (not before, picked exactly at its time), `test_next_publish_time_today_or_tomorrow` |
| IST → UTC | `test_ist_to_utc_conversion` (incl. crossing midnight), `test_schedule_api_converts_ist_and_validates`, `test_generate_time_defaults_to_45_min_before_publishing` |
| Schedule updates | `test_saving_times_in_dashboard_replaces_schedules_without_duplicates`, `test_obsolete_schedules_removed_and_pause_clears_ours` |
| Duplicate schedules / runs | Upsert keeps 5 schedules, foreign schedule untouched; `test_signed_job_callback_runs_job_once_per_slot` (redelivery skipped) |
| Retry | `test_failed_job_returns_500_so_qstash_retries`, `test_local_tick_retries_with_backoff_then_stops` (2/4/8 min, stops after 3) |
| Recovery | `test_maintenance_closes_stale_running_jobs`, `test_maintenance_step_failure_does_not_block_other_steps`, `test_expired_lease_is_taken_over` |
| Concurrent execution | `test_concurrent_triggers_run_job_once` (5 triggers → 1 run) |
| Security | `test_job_callback_rejects_bad_signatures` (wrong key, token for another job's URL, unsigned) |
| Jobs | `test_generate_in_auto_mode_schedules_for_publishing_time`, `test_generate_in_review_mode_waits_for_approval`, `test_legacy_rows_without_approval_are_never_auto_published`, `test_missed_schedule_is_not_published_late`, `test_daily_limit_respected`, `test_tick_runs_maintenance_and_due_posts`, `test_scheduler_status_endpoint`, `test_sync_without_qstash_reports_clearly` |

**Found and fixed while testing:** maintenance used to stop at the first failing step. Now every recovery step runs and failures are reported together, so QStash still retries.

## 6. Behaviour changes to know about
* **Auto Mode no longer publishes inside the build job.** Generate approves and schedules the post, and `publish_due` publishes it at Publishing time. Same outcome, but separate steps, each within the time limit.
* **Approved posts more than 12 h late are not auto-published.** The post gets a "Missed its scheduled time" note so you can reschedule. This avoids posting stale news days later after an outage.
* **Failed publishes are not retried automatically.** Phase 2 records Meta's error and the dashboard offers a safe retry.
* **Without QStash configured, nothing scheduled runs on Vercel**, except the daily maintenance safety net. The dashboard will show this in Phase 6. Locally, the in-process thread still runs everything.

## 7. Known limitations
* QStash's exact behaviour on `Upstash-Schedule-Id` upsert with a **changed destination** is documented as "settings updated", but it hasn't been tested live. The first production sync should be checked in the QStash console.
* Custom per-post times have 10-minute resolution (cost trade-off: a 1-minute tick would be 1,440 messages/day, over the free limit).
* Postgres DDL is still unverified against a real Postgres. It's in the deployment checklist.

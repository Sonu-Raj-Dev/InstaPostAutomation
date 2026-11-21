# Phase 6: Dashboard (Automation Status + Webhook Health)

Status: **implemented locally on `feat/publishing-reliability`, not committed, not deployed.**
Tests: **130 passed** (+9 dashboard tests). The UI was checked in a safe preview (database copy, no Meta token, DMs paused).

## 1. Automation page: "Systems" (replaces the old single-pipeline diagram)
The old 9-step diagram described the coupled `run_pipeline`, which no longer reflects how things run. It's replaced by **one card per independent system**, in the same card, chip and notice styles, with navigation and configuration left in place.

| System | Source of truth | Shows | Actions |
|---|---|---|---|
| Research | `jobs` kind=research | Status, last run + result, next run (from the schedule), 7-day ok/failed, latest error, live stage while running | Run now, Log |
| Content generation | `jobs` kind=generate (+ legacy `pipeline`) | same | Run now, Log |
| Publishing | `jobs` kind=publish/publish_due + `carousels` | same, plus scheduled count / next scheduled post / failed / in progress | Run now (**confirmation**: it publishes), Log, Failed posts → Approval |
| Comment monitoring | `webhook_events` (comments) | Last event, 7-day processed/failed/waiting, latest error. Next = "on each comment (webhook)" | Process waiting (sweep), Details |
| DM delivery | `dm_deliveries` | Last DM sent, guides sent, waiting, failed + uncertain, latest error | Details → Comment-to-DM |
| Analytics | `jobs` kind=analytics | same as research | Run now, Log |

* **Run now** uses the same database lease as the scheduler, so it can never overlap a scheduled run. If one holds the lease, the manual job fails with "already in progress" (tested).
* **Next run** is computed from the dashboard times, and shows "Scheduler paused" when paused.
* **Configuration** gains *Content generation time* (empty = 45 min before publishing) and *Analytics time*. Saving reports whether the QStash schedules were updated, or why not.
* The job filter adds Generate, Publish due, Analytics and Maintenance.

## 2. Webhook health panel
| Item | Source |
|---|---|
| Meta webhook verification | `webhook_verified_at`, recorded when Meta's subscribe handshake succeeds (new) |
| App secret configured | `META_APP_SECRET` present (shows that webhooks are rejected without it) |
| Last received event | `webhook_last_received_at` (UTC) |
| Last processed event | Latest `webhook_events.processed_at` |
| Last successful DM | Latest `dm_deliveries.sent_at` |
| Failed DM count | `dm_deliveries` FAILED + UNCERTAIN, with a link to review |
| QStash processing status | Token / signing keys present, event queue counts by status, schedules synced + time + error, **Sync now** |
| Subscription status (where verifiable) | Read from the Phase 7 Meta audit result. Until that check runs it says **Unknown, not checked yet** (never a fake "OK") |
| Callback URL | Shown on Vercel for copying into the Meta dashboard |

## 3. Comment-to-DM page
New **Incoming webhook events** table: real rows from `webhook_events` (time, type, sender, text, status, attempts, error), with Retry on failed events. When `META_APP_SECRET` is missing, the empty state says so instead of implying all is well.

## 4. API (new, login required)
* `GET /api/automation/overview`: every value above, from the DB and settings.
* `POST /api/automation/run/{research|generate|publish_due|analytics|maintenance}`: Run now (`publish_due` needs `confirm`).
* The webhook verify endpoint also records `webhook_verified_at`.

## 5. Tests (`tests/test_dashboard.py`, all PASS)
| Required | Test |
|---|---|
| Correct job status | `test_job_status_and_failure_message_shown` (FAILED then OK after a later success), `test_running_job_reported_live`, `test_generation_counts_legacy_pipeline_runs_too` |
| Correct failure message | same (exact error text surfaced) |
| Webhook health | `test_webhook_health_reflects_real_events` (verification recorded, secret flag, last event, queue counts, subscription "unknown") |
| DM delivery status | `test_dm_delivery_status_and_failed_count` |
| Scheduler status | `test_scheduler_status_and_next_runs` (next run present; none when paused), `test_publishing_post_counts` |
| Safe retry controls | `test_run_now_uses_lease_and_requires_confirm_for_publishing` |
| DM page events | `test_inbox_events_listing_for_dm_page` |

## 6. Found and fixed during the UI check
* At about 800 px width, long chips in the health panel spilled into the next column. Shortened the labels (details moved to a muted line underneath) and widened the columns. Re-checked: clean.

## 7. Files
`src/dashboard/app.py` (overview, run-now, verify timestamp) · `src/dashboard/static/js/pages/automation.js` (Systems, Webhook health, new config fields, job filters) · `src/dashboard/static/js/pages/dm.js` (incoming events table) · `tests/test_dashboard.py` (new).
Backups: `backups/pre_phase6/` holds `automation.js` and `dm.js` from before this phase. (Its `app.py` copy was taken *after* the API change. The pre-Phase-6 `app.py` is the Phase 5 state described in `reports/phase5_scheduler.md`.)

## 8. Limitations
* "Subscription status" only becomes concrete after the Phase 7 Meta configuration check.
* Counts are 7-day windows from `jobs.started_at` (IST text) and the UTC columns. Both are compared in their own format, so no historical data was converted.

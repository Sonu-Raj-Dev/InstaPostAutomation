# Phase 2: Publishing Test Results

Command: `python -m pytest tests -v --timeout=30` on branch `feat/publishing-reliability`, 2026-11-21

**Result: 47 passed, 0 failed** (19 existing + 28 new). Runtime ~16 s.

## How the tests stay off the real account
* `tests/conftest.py` (new) blocks **every** real HTTP request for every test (`requests.Session.request` raises). Any unmocked call fails the test instead of reaching Instagram, GitHub or an image host.
* `tests/test_publishing.py` routes all Graph calls to a stateful **FakeGraph**. It raises on any unknown URL, requires a token on Graph calls, and simulates container states, Meta errors (code, subcode, fbtrace), timeouts and an image CDN.
* `meta.reload()` is replaced in these tests, so the real token in `.env` is never read.
* Temp database per run. The real local `data/content_store.db` and production Postgres are never opened.

## Required cases → tests

| Required case | Test(s) | Result |
|---|---|---|
| Single-image publishing | `test_single_image_publish` (single container, no carousel items, UTC attempt time) | PASS |
| Carousel publishing | `test_carousel_publish_checks_every_child_then_parent`, `test_processing_delay_is_waited_out` | PASS |
| Child container failure | `test_child_container_failure_keeps_meta_error` (code 9004 / subcode 2207052 / fbtrace / HTTP 400 / slide 2 kept; no publish call) | PASS |
| Parent container failure | `test_parent_container_failure` | PASS |
| Expired token | `test_expired_token` (code 190 → "Renew it in Settings") | PASS |
| Missing permission | `test_missing_publish_permission` (scope pre-check, no containers created), `test_permission_error_from_meta_is_explained` (code 10) | PASS |
| Invalid image URL | `test_invalid_image_url_stops_before_meta` (HTTP 404), `test_wrong_content_type_rejected` (PNG), `test_non_jpeg_and_non_https_images_rejected` (http://) | PASS |
| Processing timeout | `test_processing_timeout` (stays IN_PROGRESS → failure, no publish call), `test_container_error_status` | PASS |
| Publishing timeout | `test_publish_timeout_but_live_is_marked_published` (exactly 1 publish call), `test_publish_timeout_not_live_allows_safe_retry`, `test_definite_publish_error` | PASS |
| Duplicate button clicks | `test_duplicate_button_clicks` (workflow and API both refuse; 1 publish call) | PASS |
| Concurrent publishing attempts | `test_concurrent_publishing_attempts` (6 threads → 1 success, 5 "duplicate", 1 publish call), `test_claim_is_atomic_at_db_level` | PASS |
| Recovery of stuck publishing jobs | `test_stuck_before_container_is_failed_safely`, `test_stuck_but_live_is_reconciled_to_published`, `test_stuck_not_live_becomes_retryable_then_publishes` (through the `/reconcile` API), `test_stuck_post_with_media_id_is_published_without_meta_call`, `test_recent_publishing_is_left_alone`, `test_unreachable_meta_leaves_stuck_post_untouched`, `test_stale_running_jobs_are_failed` | PASS |
| Never republish a live post on retry | `test_retry_after_failure_never_republishes_a_live_post` | PASS |
| Token never leaks into errors | `test_token_is_scrubbed_from_network_errors` | PASS |

## Existing tests
All 19 existing tests pass. **One was adapted, not removed:** `test_publish_success_records_meta_ids` used to stub `meta.publish_carousel()`, which `publish()` no longer calls (it now drives each Meta step itself). The stubs now target the step methods. Its assertions are unchanged (PUBLISHED, media id, permalink, published post is read-only).

## Manual UI check (local, safe)
Ran the dashboard against a **copy** of the local database, with no Meta token, the scheduler off and DM campaigns paused in the copy. Two posts were set up to show the new states:
* A post stuck in Publishing shows the warning and **Check status**. Clicking it moved the post to Failed with "safe to retry", and the toast confirmed it.
* A failed post shows "failed during uploading" with Meta's message, the action and the code, subcode, HTTP status and fbtrace.
* No console errors.
* The migration on the copy added the 5 columns, kept every row in all tables, and left historic timestamps unchanged.

During the check I found and fixed two wording/logic issues: the message no longer says "confirmed with Meta" when no Meta call was needed, and a stuck post that already has a media id now reconciles to Published.

## Not covered (needs your approval or a production-like environment)
* A real publish to @sonu.ai.lab (Phase 10, one approved live test).
* Postgres migration on an actual Postgres instance (run on a staging or Neon branch before production).
* Real Meta latency and rate-limit behaviour.

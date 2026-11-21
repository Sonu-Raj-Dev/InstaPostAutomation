# Phase 3: Webhook + QStash Test Results

Command: `python -m pytest tests -q --timeout=30` → **71 passed, 0 failed** (about 16 s). New file `tests/test_webhooks.py`: 24 tests.
`tests/conftest.py` blocks every real HTTP call. QStash is faked at the HTTP layer (`FakeQStash`, which asserts the publish URL). Meta signatures and QStash JWTs are generated in the tests with test-only keys.

| Requirement | Test(s) | Result |
|---|---|---|
| Verification challenge | `test_verification_challenge` | PASS |
| Require META_APP_SECRET | `test_missing_app_secret_rejects_and_stores_nothing` (503, nothing stored) | PASS |
| Verify signature, reject unsigned/invalid | `test_unsigned_and_invalid_signatures_rejected` (403, nothing stored) | PASS |
| Persist events with comment fields | `test_valid_event_is_persisted_with_comment_fields` (id, text, sender id/username, media, account, UTC receipt) | PASS |
| Unique comment id constraint | `test_unique_comment_id_constraint_at_db_level` (same comment under a different key is refused) | PASS |
| Duplicate delivery safe | `test_duplicate_delivery_is_stored_and_processed_once` | PASS |
| Concurrent comments | `test_concurrent_comments_each_stored_once` (9 parallel posts, repeated ids → each comment stored once) | PASS |
| DM events; ignore our echoes | `test_echo_messages_ignored_and_dm_taps_stored` | PASS |
| Queue on QStash (URL, auth, retries, dedup id) | `test_new_event_is_queued_on_qstash` | PASS |
| QStash unavailable → kept, recovered | `test_qstash_down_keeps_event_pending_then_sweep_recovers` (Meta still gets 200) | PASS |
| No QStash on Vercel → sweep processes | `test_sweep_processes_inline_without_qstash` | PASS |
| Signed callback, idempotent redelivery | `test_signed_callback_processes_event_once` | PASS |
| Key rotation + body hash with or without padding | `test_next_signing_key_and_unpadded_body_hash_accepted` | PASS |
| Reject bad QStash signatures | `test_bad_qstash_signatures_rejected` ×5: wrong key, wrong URL (`sub`), expired, wrong issuer, tampered body | PASS |
| Callback with no keys configured | `test_callback_without_keys_configured_rejected` | PASS |
| Concurrent processing runs once | `test_concurrent_processing_runs_handler_once` (5 workers → 1 run) | PASS |
| Retry with bounded attempts, record errors, safe manual retry | `test_failure_is_retryable_then_final` (500 ×4, then a final 200, then dashboard retry → processed) | PASS |
| Stuck processing recovered | `test_stale_processing_is_reclaimed` | PASS |
| Events with no campaign | `test_no_campaign_event_is_ignored_not_failed` | PASS |
| Admin endpoints need login | `test_inbox_api_requires_login_paths_and_reports_health` | PASS |

**Existing test adapted, not removed:** `test_webhook_verify_and_wake` used to post an *unsigned* webhook and expected an inline scan. That behaviour is now deliberately rejected. The test now signs the request and confirms the campaign scan still runs (through the inbox worker). Its assertion is unchanged.

**Not covered here:** real Meta delivery, real QStash delivery and quota behaviour, and running on Postgres. These go in the Phase 10 deployment checklist and the approved live test.

# Instagram Automation: Test Results (Phase 9)

Command: `python -m pytest tests -v --timeout=60` on `feat/publishing-reliability`, 2026-11-21.
**Result: 140 passed · 0 failed · 0 skipped** (about 30 s). The real headless-browser render test also ran and passed.

| File | Tests | Scope |
|---|---|---|
| `test_app.py` | 19 | Original suite (4 adapted to new internals, none removed) |
| `test_publishing.py` | 28 | Phase 2 publishing |
| `test_webhooks.py` | 24 | Phase 3 webhook inbox + QStash |
| `test_dm_engine.py` | 26 | Phase 4 comment-to-DM |
| `test_scheduler.py` | 24 | Phase 5 scheduler |
| `test_dashboard.py` | 9 | Phase 6 dashboard |
| `test_meta_audit.py` | 6 | Phase 7 Meta audit |
| `test_security.py` | 4 | Phase 8 security |

## Safety of the test run
* `tests/conftest.py` makes **every real HTTP request fail** in every test. Meta, QStash and image CDNs are fakes that raise on unknown URLs.
* Temporary database per run; the real local DB and production Postgres are never touched.
* **No real Instagram publish or DM** was made at any point.

## Required categories → tests

### Publishing
| Case | Test(s) |
|---|---|
| Single image | `test_single_image_publish` |
| Carousel | `test_carousel_publish_checks_every_child_then_parent`, `test_processing_delay_is_waited_out` |
| Failed publishing | `test_child_container_failure_keeps_meta_error`, `test_parent_container_failure`, `test_definite_publish_error`, `test_container_error_status` |
| Expired token | `test_expired_token` |
| Permission errors | `test_missing_publish_permission`, `test_permission_error_from_meta_is_explained` |
| Invalid image URL | `test_invalid_image_url_stops_before_meta`, `test_wrong_content_type_rejected`, `test_non_jpeg_and_non_https_images_rejected` |
| Processing timeout | `test_processing_timeout` |
| Publishing timeout | `test_publish_timeout_but_live_is_marked_published`, `test_publish_timeout_not_live_allows_safe_retry` |
| Duplicate publishing | `test_duplicate_button_clicks`, `test_concurrent_publishing_attempts` (6 → 1), `test_claim_is_atomic_at_db_level`, `test_retry_after_failure_never_republishes_a_live_post` |
| Recovery | `test_stuck_*` (5 tests), `test_recent_publishing_is_left_alone`, `test_stale_running_jobs_are_failed` |

### Webhooks
| Case | Test(s) |
|---|---|
| Verification challenge | `test_verification_challenge` |
| Valid signature | `test_valid_event_is_persisted_with_comment_fields` |
| Invalid signature | `test_unsigned_and_invalid_signatures_rejected` |
| Missing app secret | `test_missing_app_secret_rejects_and_stores_nothing` |
| Duplicate event | `test_duplicate_delivery_is_stored_and_processed_once`, `test_unique_comment_id_constraint_at_db_level` |
| Concurrent comments | `test_concurrent_comments_each_stored_once`, `test_concurrent_processing_runs_handler_once` |
| Event persistence | `test_valid_event_…`, `test_qstash_down_keeps_event_pending_then_sweep_recovers` |
| QStash signatures | `test_signed_callback_processes_event_once`, `test_next_signing_key_and_unpadded_body_hash_accepted`, `test_bad_qstash_signatures_rejected` ×5 |

### DM
| Case | Test(s) |
|---|---|
| AGENT | `test_agent_uppercase_triggers_one_private_reply` |
| agent | `test_lowercase_agent_matches`, `test_partial_words_do_not_match` ×4 |
| Multiple keywords | `test_multiple_keywords_per_campaign` |
| Duplicate comment | `test_duplicate_comment_event_sends_once`, `test_concurrent_workers_same_comment_send_once`, `test_live_scan_uses_the_same_claim` |
| Invalid recipient | `test_invalid_recipient_is_final_failure_with_details` |
| Successful private reply | `test_agent_uppercase_…`, `test_tap_delivers_guide_with_link`, `test_follow_gate_then_delivery` |
| Failed private reply | `test_transient_failure_retried_by_queue_then_succeeds`, `test_retry_attempts_are_bounded`, `test_uncertain_reply_is_not_auto_retried`, `test_manual_retry_of_failed_delivery` |
| Multiple campaigns | `test_multiple_campaigns_on_one_post_send_only_one_reply` |

### Scheduler
| Case | Test(s) |
|---|---|
| Exact scheduled time | `test_schedules_built_from_dashboard_times`, `test_publish_due_exact_time` |
| IST → UTC | `test_ist_to_utc_conversion`, `test_schedule_api_converts_ist_and_validates` |
| Schedule updates | `test_saving_times_in_dashboard_replaces_schedules_without_duplicates`, `test_obsolete_schedules_removed_and_pause_clears_ours` |
| Duplicate schedules | same + `test_signed_job_callback_runs_job_once_per_slot` |
| Retry | `test_failed_job_returns_500_so_qstash_retries`, `test_local_tick_retries_with_backoff_then_stops` |
| Recovery | `test_maintenance_closes_stale_running_jobs`, `test_maintenance_step_failure_does_not_block_other_steps`, `test_expired_lease_is_taken_over` |
| Concurrent execution | `test_concurrent_triggers_run_job_once` |

### Dashboard
| Case | Test(s) |
|---|---|
| Correct job status | `test_job_status_and_failure_message_shown`, `test_running_job_reported_live`, `test_generation_counts_legacy_pipeline_runs_too` |
| Correct failure message | `test_job_status_and_failure_message_shown` |
| Webhook health | `test_webhook_health_reflects_real_events`, `test_audit_endpoint_feeds_webhook_health` |
| DM delivery status | `test_dm_delivery_status_and_failed_count` |
| Scheduler status | `test_scheduler_status_and_next_runs`, `test_scheduler_status_endpoint`, `test_publishing_post_counts` |

### Security (Phase 8)
`test_admin_endpoints_require_login` (16 endpoints → 401), `test_public_endpoints_verify_their_own_signatures`, `test_tokens_never_returned_by_the_api`, `test_stored_error_text_is_scrubbed`, `test_token_is_scrubbed_from_network_errors`, `test_user_token_audit_reports_gaps_and_never_leaks_tokens`.

## Other verification
* **Mutation check:** with the DM claim guard disabled, the duplicate tests fail. The guard was restored.
* **Migration on a real data copy:** local DB copy migrated twice; existing rows and values identical; additive only.
* **Static Postgres review:** all DDL idempotent, every new table has `id` (needed by the INSERT … RETURNING path), no literal `%` in SQL.
* **UI in a safe preview** (DB copy, no token, DMs off): approval states, Check status, failure details, DM page (history, retry, events), Automation Systems + Webhook health. Two layout and wording issues were found and fixed.
* **Live read-only Meta audit** (GET only) with the local token. Results are in `meta_configuration_checklist.md`.
* **Unused-import check** on changed code: 2 removed.

## Bugs found and fixed during testing
1. Stuck-post recovery said "confirmed with Meta" when no Meta call was made. A post with a media id now always reconciles to Published.
2. Maintenance stopped at the first failing step. Now every step runs and errors are reported together.
3. The Meta audit called an SSL/network error "token not valid", and a failed check "not subscribed". Both now say "couldn't check" with the real reason.
4. Health panel chips overflowed at about 800 px width.

## Not covered (needs production or your approval)
* Real Postgres execution of the migration (deployment checklist step 2).
* Real QStash delivery, schedules and quota behaviour.
* Real Meta webhook delivery, private reply and DM (depends on the Meta configuration steps).
* **One approved live publish** and **one approved comment-to-DM test** (deployment checklist steps 9–10).

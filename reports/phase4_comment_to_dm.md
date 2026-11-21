# Phase 4: Comment-to-DM Engine (Implementation + Tests)

Status: **implemented locally on `feat/publishing-reliability`, not committed, not deployed. No real DM sent.**
Tests: **97 passed** (19 original + 28 Phase 2 + 24 Phase 3 + 26 Phase 4), with all real network access blocked.

## 1. Flow

```
comment "AGENT" → Meta webhook → verify signature → webhook_events (unique comment id) → QStash → process_event (claimed)
  → dm_engine.handle_comment_event
      1. campaigns for this post (active)                 none → IGNORED
      2. GET /{comment-id} from Instagram                 can't read (deleted/forged) → IGNORED, nothing sent
      3. keyword match (all keywords, case-insensitive, whole word; first matching campaign wins: Meta allows ONE private reply per comment)
      4. eligibility: not our own account · comment ≤ 7 days old · this person not already served by this campaign
      5. CLAIM: INSERT dm_deliveries(status=SENDING) with UNIQUE(comment_id)  ← only one worker can win
      6. private reply (opener + "Send me the access" button) → AWAITING_TAP / FAILED / UNCERTAIN, with Meta error details
      7. history row for every step (dm_delivery_log)
their tap (a DM from them opens Meta's 24 h window) → webhook → dm_engine.handle_message_event
      CLAIM AWAITING_* → DELIVERING → follow gate (nudge, max 3) or guide text + guide link + guide images → RESOURCE_SENT
```

The **live scan** button (and the local poller) now go through the same `deliver_for_comment` claim, so a scan and a webhook can never both message the same comment.

## 2. Requirements → implementation

| Requirement | How |
|---|---|
| Multiple keywords per campaign | New `campaigns.keywords` (comma list, up to 10). The existing `keyword` stays the main one and is **unchanged** for existing campaigns |
| Case-insensitive matching | Whole-word regex, case-insensitive: `agent`/`AGENT!` match, `agents`/`reagent` don't (tested) |
| Per-campaign message templates | The existing per-campaign `private_reply`, `follow_gate_message`, `resource_pack` and `public_reply_text`, now with `{username}`, `{keyword}` and `{guide_url}` placeholders |
| Guide link configuration | New `campaigns.guide_url` (https only), added to the guide DM unless it's already in the text. The existing generated guide images still go out |
| Delivery history | New `dm_delivery_log` (UTC): claimed → private_reply → follow_gate → deliver, with result and detail. "History" button per delivery |
| Retry only when safe | **Transient** Meta errors (rate limits 4/17/32/613, 5xx) → the queue retries, max 3 send attempts per comment. **Final** errors (permission, outside window, unavailable user) → no automatic retry. **Uncertain** (timeout: Meta may have sent it) → `UNCERTAIN`, never auto-retried. A manual retry needs an explicit "may double-message" confirmation |
| Failed delivery details | `error` (message + code/subcode/fbtrace) and `last_error_json` (full structured error) |
| Duplicate prevention across workers | `INSERT … status=SENDING` on `UNIQUE(comment_id)` before sending. Tap handling claims `AWAITING_* → DELIVERING` with a conditional UPDATE. Verified by concurrency tests, and a mutation test (claim disabled → tests fail) |
| Commenter eligibility | Own account → `SKIPPED_SELF`. Over 7 days → `SKIPPED_EXPIRED`. Already served by this campaign → `SKIPPED_DUPLICATE_USER`. Comment must exist on Instagram |
| Dashboard reflects real status | Deliveries table shows every new status (Sending, Waiting for tap, Not confirmed by Meta, Already served…), errors, History and Retry |
| Preserve existing campaigns and guides | Additive columns only. The legacy AGENT campaign and its deliveries are untouched (checked on a DB copy) |

## 3. Meta rules respected
* At most **one private reply per comment**, only **within 7 days** of the comment.
* Every later message (follow-gate nudge, guide) answers a DM **the person sent** (their tap), inside the 24-hour window.
* No unsolicited outbound DMs anywhere in the engine.
* Messaging endpoint: `me/messages` by default, overridable with **`META_MESSAGING_NODE`** (for example the Page id). Which one is correct depends on the token type. Phase 7 audits this.

## 4. Files
| File | Change |
|---|---|
| `src/automation/dm_engine.py` *(new)* | The engine above |
| `src/automation/comment_responder.py` | Structured Meta errors on every call (`last_error`, token scrubbed); `get_comment()`; configurable messaging node; guide link in the guide DM; live scan uses the engine's claim |
| `src/automation/webhook_inbox.py` | Default handler → `dm_engine.handle_event` (replaces the Phase 3 bridge) |
| `src/db/migrate_v2.py` | Additive: `campaigns.keywords`, `campaigns.guide_url`; `dm_deliveries.event_id/sent_at/retryable/last_error_json`; new `dm_delivery_log` |
| `src/dashboard/app.py` | Campaign validation for keywords and guide link; `GET /api/deliveries/{id}/log`; `POST /api/deliveries/{id}/retry` (UNCERTAIN needs `confirm_uncertain`) |
| `src/dashboard/static/js/pages/dm.js` | Extra keywords and guide link fields, keyword chips, History and Retry per delivery, all new statuses (same design) |
| `src/dashboard/static/js/ui.js` | Badge labels for the new statuses |
| `tests/test_dm_engine.py` *(new)* | 26 tests |
| `tests/test_app.py` | `test_webhook_verify_and_wake` stubs moved to the engine's calls. Assertion kept, plus a check that a delivery was recorded |

Backups of the changed DM page and responder: `backups/pre_phase4/`.

## 5. Tests (all PASS)

| Required case | Test |
|---|---|
| AGENT | `test_agent_uppercase_triggers_one_private_reply` (also checks `{username}`/`{keyword}` rendering and the button) |
| agent | `test_lowercase_agent_matches`; `test_partial_words_do_not_match` ×4 |
| Multiple keywords | `test_multiple_keywords_per_campaign` |
| Multiple campaigns | `test_multiple_campaigns_on_one_post_send_only_one_reply` |
| Duplicate comment | `test_duplicate_comment_event_sends_once`, `test_concurrent_workers_same_comment_send_once` (6 workers → 1 reply), `test_live_scan_uses_the_same_claim` |
| Invalid recipient | `test_invalid_recipient_is_final_failure_with_details` (code 10 / subcode 2534022 / fbtrace kept, no retries, history recorded) |
| Successful private reply | `test_agent_uppercase…`, `test_tap_delivers_guide_with_link` |
| Failed private reply | `test_transient_failure_retried_by_queue_then_succeeds`, `test_retry_attempts_are_bounded`, `test_uncertain_reply_is_not_auto_retried`, `test_manual_retry_of_failed_delivery` |
| Eligibility | `test_same_person_second_comment_is_not_messaged_again`, `test_own_account_comment_skipped`, `test_comment_older_than_7_days_skipped`, `test_forged_or_deleted_comment_is_never_messaged` |
| Guide delivery | `test_tap_delivers_guide_with_link`, `test_follow_gate_then_delivery`, `test_concurrent_taps_deliver_once`, `test_message_from_stranger_is_ignored` |
| Existing data | `test_existing_campaign_and_keyword_preserved`, `test_campaign_validation` |

**Mutation check:** I temporarily disabled the duplicate-claim guard, and the two duplicate tests failed. The guard was restored, and the suite is green.

## 6. Known limitations
* **Same person, two different comments arriving at the same instant:** both can pass the "already served" check before either is claimed, so that person may get two private replies (one per comment, which Meta allows). Each individual comment is still messaged at most once. Fixing it fully needs a per-person claim; that's a small follow-up if you want it.
* **Not run against real Meta:** private-reply eligibility and the right messaging node depend on the token type and app configuration (Phase 7).
* `UNCERTAIN` deliveries need a human decision. There's no Meta API to ask "did my private reply arrive", so the app won't guess.

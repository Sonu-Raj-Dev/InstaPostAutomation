# Feature Status

Legend: ✅ working & tested · 🟡 working, stated limit · ⛔ blocked externally · ❌ not implemented

Tested 2026-11-20 against the real DB, live GitHub/HN/Hugging Face APIs, headless Edge, and the (expired) Meta token.

| Area | Feature | Status | Evidence / limit |
|---|---|---|---|
| Command Center | Three.js engine, 9 workflow nodes, hover tooltips, click → page (camera fly-to) | ✅ | Verified in browser; WebGL-less fallback list; reduced-motion = static frame |
| | Node status from real data; active stage + pulses only while a real job runs | ✅ | Watched a research job move Intelligence → GitHub → Tools → Verification |
| | KPIs, schedule, latest creative, activity feed | ✅ | All from `/api/state` |
| Daily Intelligence | Research run (HN Algolia, GitHub Search, Hugging Face) | ✅ | Runs found 40 + 24 stories; 39/40 and 21/24 sources verified |
| | Source verification, og:image, de-duplication, scoring, suggested format | ✅ | Legacy hand-written entries re-verified: Wan2.1 8,200→17,466 stars, Kokoro 16,400→10,260, HyperFrames 2,400→10 |
| | Bot-blocked sources (e.g. Reuters 401) | 🟡 | Marked "Blocks bots", not counted as verified |
| Creator Studio | Draft from topic, adaptive format (1–10, never padded) | ✅ | Tests + real drafts (5-slide repo, 3-slide news) |
| | Live preview, slide nav, zoom, preview-all, edit text/facts/steps, layouts, move/duplicate/delete/add | ✅ | Browser |
| | Replace image (upload) / use source preview | ✅ | Endpoint + UI; 8 MB, jpg/png/webp/gif |
| | Regenerate slide / whole post / change slide count | ✅ | Re-fetches README commands; alternate layouts, no invented facts |
| | Render to 1080×1350 JPG | ✅ | ~10 s per deck (one Edge launch); real-render test passes |
| | Reel creation | 🟡 | Recommended for video tools, but the app can't record/edit video — carousel fallback |
| | Copywriting | 🟡 | Deterministic templates from verified fields; no LLM configured |
| Approval | Queue by status, slide lightbox, caption edit, sources, resource pack, QC, reject w/ reason, regenerate | ✅ | Browser + tests |
| | Approve & publish | ⛔ | Code path tested with mocks (success + failure); live publish blocked: Meta token expired 2026-11-20 05:00 PST |
| | Never PUBLISHED without Meta media id; real permalink fetched | ✅ | Test `test_publish_failure_never_marks_published` |
| Automation | IST scheduler (research 17:30, build 19:00), grace window, once/day | ✅ | `test_scheduler_fires_once_inside_window` |
| | Config with validation, Auto Mode confirmation | ✅ | Test + UI |
| | Jobs (active/completed/failed), failure reasons, logs | ✅ | Browser |
| Comment-to-DM | Campaign CRUD, keyword validation, linked post, follow gate, resource pack | ✅ | Tests + UI |
| | Dry-run scan; private-only; dedupe | ✅ | `test_dm_private_only_follow_gate_and_dedupe` |
| | Live sending | ⛔ | Needs a valid token **with** `instagram_manage_messages`; untested live |
| | Follower verification | 🟡 | Only after the person DMs back (Meta rule); shown as "Awaiting DM reply" until then |
| Analytics | Reach, followers, interactions, saves, shares, per-post, category, format | ⛔ | Implemented against Graph API v22; shows "not connected" until token renewed — no placeholder numbers |
| Settings | Diagnostics (validity, expiry, scopes, capabilities) | ✅ | Shows the real expiry error |
| | Token renewal | 🟡 | `META_APP_SECRET` is empty in `.env`: pasted tokens are saved as issued (validated against the configured account) instead of exchanged for 60-day tokens |
| | Identity/defaults/cost controls with validation | ✅ | |
| Responsive | Desktop 1440, laptop, tablet (icon rail), mobile 390 (drawer) | ✅ | No horizontal overflow measured at 390 px |

## v4 — simple flow (2026-11-20, after user feedback)

| Feature | Status | Evidence / limit |
|---|---|---|
| 3-step Create post (choose → review → publish) | ✅ | Walked in browser: pack of 3 Video & Animation tools → review → render → publish checklist |
| Pack posts (2–8 tools, numbered like reference “Comment PACK” posts) | ✅ | `test_pack_post_and_guide`; real render of post #9 |
| Bright 3D post style with real README screenshots (banners/logos/badges rejected by size + aspect) | ✅ | Rendered decks in `docs/screenshots/pack-post-3d.jpg` |
| DM guide document rendered as images + copyable text (real install commands, features, screenshots, link) | ✅ | `docs/screenshots/dm-guide-pages.jpg` |
| Auto-created DM campaign on publish, auto-polling every N min (no manual scans) | 🟡 | Tested with mocks; live sending not yet observed (no live comments on a live post during testing) |
| Button flow: “Send me the access” → follow check → “I'm following ✅” → guide | 🟡 | `test_dm_button_flow_follow_gate_and_guide_delivery`; button rendering on private replies depends on Meta — falls back to plain text if rejected |
| Own comments never trigger DMs; dead posts auto-pause their campaign | ✅ | Observed: campaign for deleted media 18146778493590351 auto-paused |
| Slide handle follows connected account (@sonu.ai.lab) | ✅ | |

## Known limitations
* GitHub search is unauthenticated (10 req/min); set `GITHUB_TOKEN` in `.env` for more headroom. GitHub's preview-image service can return 429 for thumbnails; they hide gracefully.
* The Instagram handle in the brief (`sonu.ai.lab`) differs from the configured publishing account (`@sonu2967_02`, id in `.env`). The app only ever publishes to the configured id.
* Root scripts `publish_post.py`, `publish_live_carousel.py`, `render_white_red.py` are the old one-off scripts (hardcoded captions); the UI no longer uses them.

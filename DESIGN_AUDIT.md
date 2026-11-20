# Design & Technical Audit — Instagram CMS (pre-redesign)

Audited 2026-11-20 against the code on disk, the SQLite store, and live read-only Meta Graph API calls.

## 1. Stack

| Layer | Found |
|---|---|
| Frontend | No framework. One HTML string inside `src/dashboard/app.py` (lines 126–1104), Tailwind **Play CDN** (runtime compiler), Font Awesome CDN, inline vanilla JS. No build step, no `package.json`. |
| Backend | FastAPI 0.141 + uvicorn, Python 3.13. Single module `src/dashboard/app.py`. |
| Routing | Hash tabs: `#dashboard #research #creator #queue #settings #analytics`. `#creator` = "Content Studio". |
| Storage | SQLite `data/content_store.db` — tables `topics`(9 rows), `carousels`(4), `settings`(6), `post_insights`(0). JSON file `data/replied_comments.json` for DM dedupe. |
| Rendering | Pillow (`generator/adaptive_carousel.py`) drawing slides to `output/current_carousel/slide_NN.jpg`. Two older generators (`bento_carousel.py`, `white_red_carousel.py`) used only by root scripts. |
| Publishing | `meta_graph_client.py` — Graph API v22.0 4-step carousel flow (child containers → parent → poll FINISHED → `media_publish`). Images staged to freeimage.host / catbox via `utils/media_uploader.py`. |
| Research | `research/harvester.py` — GitHub search API + Hacker News top stories + a hand-written "curated" list. |
| Scheduling | `scheduler/daily_runner.py` — a pipeline function. **No scheduler exists**; it only runs on button click or `python daily_runner.py`. |
| QC | `qc/evaluator.py` — keyword heuristics, 7 checks (docs claim 12). |
| DM | `automation/comment_responder.py` — scans comments, **always posts a public reply**, checks `is_user_follow_business`, sends Private Reply. |
| Secondary | `metricool_client.py`, `mcp_server.py` (FastMCP tools). Untouched by this redesign. |

## 2. Live integration state

* Meta token in `.env` is a **short-lived token that expired 2026-11-20 05:00 PST** (error 190/463). Every Graph call currently fails. The old UI showed "Meta API Connected" regardless.
* Headless Microsoft Edge and Chrome are installed → usable for HTML→JPG slide rendering.
* No LLM key configured (`anthropic` package installed, no `ANTHROPIC_API_KEY`).

## 3. Placeholder / fake behaviour found

| Where | Problem |
|---|---|
| Sidebar | "Meta API Connected" hardcoded green. |
| Dashboard | Falls back to a hardcoded Wan2.1 headline + QC 98 when queue is empty. Slide buttons hardcoded to 5. |
| Approval Queue | Entire post is static HTML: fixed headline, QC "100/100", fixed caption, "2 Posts Ready" badge, second post hardcoded. Reject = `alert()`. "Load in Content Studio" = `alert()`. |
| `/api/meta/publish-live-deck` | Ignores the queue. Always publishes `output/current_carousel/*` with a **hardcoded Wan2.1 caption** and records headline "Wan2.1…". |
| Permalink | Built as `instagram.com/p/{media_id}` — media id is not a shortcode; link is wrong. Real `permalink` field never fetched. |
| `/api/meta/check-comments` | Hardcoded two post IDs and keyword `AGENT`; always posts public replies; DM text hardcoded to an unrelated "Autonomous Engineer" pack. |
| `/api/carousel/regenerate-slide` | Uses highest-scored topic, not the carousel being edited; slide_count hardcoded 5. |
| Harvester "curated" list | 4 entries with invented star counts and 2025 dates written in code; one repo path (`hyperframes/hyperframes`) unverified. |
| GitHub query | Hardcoded `pushed:>2025-01-01`. |
| Format recommender | Any title containing "video" → "REEL" with 1 slide, but the generator produces a still deck. |
| Pipeline QC | Evaluates **fake slide data** (`"demo point"`, `"sample"`), so QC score is meaningless. |
| Settings | Publish time is a read-only text field; QC threshold is static text. |
| Meta Insights | Dumps raw JSON. `get_account_insights` asks for `profile_views` with `period=day` (deprecated combination in v22). |
| Copy | `alert()` used for every success/error. |

## 4. Visual audit

* Generic dark admin template: equal-weight bento cards, Instagram pink→red gradient on every primary button, emoji/icons on every heading.
* Typography: system font, mostly 10–12 px mono labels; low hierarchy.
* No responsive layout: fixed 256 px sidebar, `grid-cols-4` metrics, `grid-cols-3` main — overflows on tablet/mobile.
* No loading/empty/error states beyond `alert()`.
* Slide output (Pillow): warm parchment grid with crimson bar; text-heavy, system fonts, no real imagery.

## 5. Keep

FastAPI app + SQLite schema, Meta 4-step publish client, image staging uploader, harvester structure, settings table, Review-mode default, `metricool_client.py`, `mcp_server.py`, root scripts.

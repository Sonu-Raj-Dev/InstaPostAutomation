# Implementation Plan — SONU AI LAB command center

## Architecture decisions

* **Keep FastAPI + SQLite.** No new backend, no new database. Schema additions via the existing `db/migrate_v2.py` pattern (idempotent `ALTER TABLE` / `CREATE TABLE IF NOT EXISTS`), run at app start.
* **Frontend stays build-free.** The app has no Node toolchain; adding React/Vite would be a migration for fashion. Instead: static ES modules served by FastAPI from `src/dashboard/static/`. Three.js and Lucide icons are **vendored** into `static/vendor/` (no CDN dependency at runtime except Google Fonts, which fall back to system fonts).
* **Real Three.js** (`static/js/scene.js`) — one scene, shared geometries/materials, DPR capped at 1.5, paused when off-screen or tab hidden, static frame under `prefers-reduced-motion`, DOM fallback when WebGL is unavailable. Node state comes from `/api/state`; active stage comes from real `jobs` rows.
* **Creative engine = HTML templates rendered by headless Edge.** `generator/html_slides.py` turns `slide_data_json` into HTML. The Studio previews that exact HTML in a scaled iframe (instant, WYSIWYG); "Render" screenshots all slides in one headless-Edge launch and crops to 1080×1350 JPGs. Falls back to the existing Pillow generator if no Chromium browser exists.
* **Jobs table** records every research / pipeline / render / publish / DM-scan run with stage, progress, log and error — this is what the 3D scene and Automation Studio display.
* **In-process scheduler thread** (Asia/Kolkata) fires research at `research_time` and the pipeline at `target_publish_time`. Review Mode stays default; Auto Mode needs an explicit confirmation in the UI.

## Stages

1. Audit → `DESIGN_AUDIT.md`, `FEATURE_STATUS.md` ✔
2. Design system → CSS tokens in `static/css/app.css` (color, type scale, spacing, radius, elevation, motion), Lucide icon set, 3D spec (below).
3. Command Center + 3D scene.
4. Creator Studio: three-panel workspace, adaptive format, per-slide edit/regenerate/replace image, caption/hashtags/CTA/resource pack, quality score, save/submit.
5. Intelligence, Approval, Automation, Comment-to-DM, Analytics, Settings pages.
6. Backend wiring: JSON API per page, remove every hardcoded caption / post id / status.
7. Visual pass in browser at desktop + mobile widths.
8. Functional tests (`tests/test_api.py`, FastAPI TestClient, isolated temp DB) + manual walkthrough.

## Backend API (new / changed)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | Overview counts, settings, schedule, meta status (cached), node states, active job, activity |
| GET | `/api/topics` | Research list, filter by category |
| POST | `/api/topics/{id}/verify` | Re-check URL, publication date, GitHub stats |
| POST | `/api/research/run` | Background research job |
| GET | `/api/jobs`, `/api/jobs/{id}` | Job history / live progress |
| GET/POST | `/api/carousels` | List / create draft from topic |
| GET/PUT | `/api/carousels/{id}` | Read / update slides, caption, design, CTA, resource pack |
| GET | `/api/carousels/{id}/slides/{n}.html` | Live HTML of one slide |
| POST | `/api/carousels/{id}/render` | Render all or one slide to JPG |
| POST | `/api/carousels/{id}/slides/{n}/image` | Replace slide image (upload) |
| POST | `/api/carousels/{id}/submit` `/reject` `/publish` | Workflow transitions; publish is a job, `PUBLISHED` only after Meta returns a media id |
| GET/POST | `/api/settings` | Validated settings |
| GET | `/api/meta/diagnostics` | Token validity, expiry, scopes, account |
| POST | `/api/meta/token` | Exchange a pasted short-lived token for a 60-day token and store it in `.env` |
| GET | `/api/analytics` | Account + per-media insights (only real data) |
| CRUD | `/api/campaigns` | Comment-to-DM campaigns |
| POST | `/api/campaigns/{id}/scan` | Dry-run (preview) or live scan |

## 3D scene spec

* Core: icosahedron (detail 3) with a fresnel/noise shader, wireframe shell, 3 tilted energy rings.
* 9 workflow nodes on an inclined ellipse, in pipeline order; sequential links + spokes to the core; small pulse sprites travel along links only when a real job is running (stage → node map), otherwise a slow idle drift.
* ~700 background particles (one `Points` draw call).
* Hover: raycast → node scales, its links brighten, HTML tooltip shows name/status/description. Click → route to the node's page.
* Budget: < 40 draw calls, DPR ≤ 1.5, `IntersectionObserver` + `visibilitychange` pause, full disposal on route change.

"""SONU AI LAB — command center API + static frontend (FastAPI).

Frontend: src/dashboard/static (build-free ES modules, vendored Three.js + Lucide).
Run:      python src/dashboard/app.py   → http://127.0.0.1:8000
"""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from config import CATEGORIES, ENV_PATH, OUTPUT_DIR  # noqa: E402
from db.migrate_v2 import migrate  # noqa: E402

migrate()

import workflow  # noqa: E402
from automation.comment_responder import CommentResponder  # noqa: E402
from generator import creative  # noqa: E402
from scheduler import daily_runner  # noqa: E402
from store import (execute, get_settings, log_event, now_ist, one, query, recover_stale_jobs,  # noqa: E402
                   set_setting, start_job, ts)

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="SONU AI LAB")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
responder = CommentResponder()
meta = workflow.meta


@app.middleware("http")
async def _revalidate_static(request: Request, call_next):
    """Static assets revalidate via ETag on every load, so UI updates are never masked by heuristic caching."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.on_event("startup")
def _startup():
    recover_stale_jobs()
    if os.getenv("CMS_DISABLE_SCHEDULER") != "1":
        daily_runner.start_scheduler()


@app.exception_handler(Exception)
async def _any_error(_, exc: Exception):
    return JSONResponse(status_code=500, content={"success": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})


@app.exception_handler(ValueError)
async def _value_error(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


async def body(req: Request) -> Dict[str, Any]:
    try:
        return await req.json()
    except Exception:
        return {}


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ meta status cache
_meta_cache: Dict[str, Any] = {"at": 0, "data": None}
_meta_lock = threading.Lock()


def meta_status(force: bool = False) -> Dict[str, Any]:
    with _meta_lock:
        if force or not _meta_cache["data"] or time.time() - _meta_cache["at"] > 600:
            meta.reload()
            d = meta.diagnostics()
            _meta_cache.update(at=time.time(), data=d)
            if (d.get("account") or {}).get("username"):
                set_setting("connected_handle", "@" + d["account"]["username"])
        return _meta_cache["data"]


# ------------------------------------------------------------------ overview
@app.get("/api/state")
def api_state(refresh_meta: bool = False):
    today = now_ist().strftime("%Y-%m-%d")
    cnt = lambda sql, a=(): one(sql, a)["n"]  # noqa: E731
    by_status = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM carousels GROUP BY status")}
    counts = {
        "topics_total": cnt("SELECT COUNT(*) n FROM topics"),
        "discovered_today": cnt("SELECT COUNT(*) n FROM topics WHERE verified_date=?", (today,)),
        "verified_today": cnt("SELECT COUNT(*) n FROM topics WHERE verified_date=? AND verification_status='VERIFIED'", (today,)),
        "verified_total": cnt("SELECT COUNT(*) n FROM topics WHERE verification_status='VERIFIED'"),
        "unverified_total": cnt("SELECT COUNT(*) n FROM topics WHERE verification_status!='VERIFIED'"),
        "drafts": by_status.get("DRAFT", 0), "pending": by_status.get("PENDING_APPROVAL", 0),
        "published": by_status.get("PUBLISHED", 0), "rejected": by_status.get("REJECTED", 0),
        "failed": by_status.get("PUBLISH_FAILED", 0),
        "generated_today": cnt("SELECT COUNT(*) n FROM carousels WHERE created_at LIKE ?", (today + "%",)),
        "rendered": cnt("SELECT COUNT(*) n FROM carousels WHERE rendered_at!=''"),
        "campaigns_active": cnt("SELECT COUNT(*) n FROM campaigns WHERE active=1"),
        "dm_sent": cnt("SELECT COUNT(*) n FROM dm_deliveries WHERE status='RESOURCE_SENT'"),
        "by_source": {r["source_kind"] or "legacy": r["n"] for r in query("SELECT source_kind, COUNT(*) n FROM topics GROUP BY source_kind")},
    }
    s = get_settings()
    m = meta_status(refresh_meta)
    jobs = query("SELECT id, kind, trigger, status, stage, progress, started_at, finished_at, error FROM jobs ORDER BY id DESC LIMIT 12")
    week = query("SELECT status FROM jobs WHERE started_at >= date('now','-7 day')")
    ok = sum(j["status"] == "SUCCESS" for j in week)
    pend = one("SELECT AVG(quality_score) a FROM carousels WHERE status IN ('PENDING_APPROVAL','DRAFT') AND slide_data_json!=''")["a"]
    last_ok_research = one("SELECT finished_at FROM jobs WHERE kind='research' AND status='SUCCESS' ORDER BY id DESC LIMIT 1")
    return {
        "brand": s.get("brand_name", "SONU AI LAB"), "handle": workflow.handle(),
        "mode": s.get("publishing_mode", "REVIEW"), "settings": s, "counts": counts,
        "schedule": {**daily_runner.next_runs(), "research_time": s.get("research_time"), "publish_time": s.get("target_publish_time"),
                     "enabled": s.get("scheduler_enabled", "1") == "1", "last_research_ok": (last_ok_research or {}).get("finished_at")},
        "meta": {"token_valid": m.get("token_valid"), "username": (m.get("account") or {}).get("username"),
                 "error": m.get("error"), "expires_at": (m.get("token") or {}).get("expires_at"),
                 "capabilities": m.get("capabilities", {}), "checked_at": int(_meta_cache["at"])},
        "jobs": jobs, "running": [j for j in jobs if j["status"] == "RUNNING"],
        "dm": {"auto": s.get("auto_dm", "1") == "1", "last_poll": s.get("dm_last_poll", ""), "last_error": s.get("dm_last_error", ""),
               "active": counts["campaigns_active"], "sent": counts["dm_sent"]},
        "health": {"jobs_7d": len(week), "success_7d": ok, "rate": round(100 * ok / len(week)) if week else None,
                   "avg_qc": round(pend) if pend else None},
        "activity": query("SELECT * FROM events ORDER BY id DESC LIMIT 20"),
        "latest": (workflow.load_carousel(r["id"]) if (r := one("SELECT id FROM carousels WHERE slide_data_json!='' ORDER BY id DESC LIMIT 1")) else None),
        "categories": CATEGORIES,
    }


# ------------------------------------------------------------------ research
@app.get("/api/topics")
def api_topics(category: str = "", status: str = "", q: str = "", limit: int = 200):
    sql, args = "SELECT * FROM topics WHERE 1=1", []
    if category:
        sql += " AND category=?"; args.append(category)
    if status:
        sql += " AND status=?"; args.append(status)
    if q:
        sql += " AND (title LIKE ? OR description LIKE ?)"; args += [f"%{q}%", f"%{q}%"]
    rows = query(sql + " ORDER BY verified_date DESC, opportunity_score DESC LIMIT ?", args + [min(limit, 500)])
    for r in rows:
        r["facts"] = json.loads(r.get("facts_json") or "[]")
        r["drafts"] = [x["id"] for x in query("SELECT id FROM carousels WHERE topic_id=?", (r["id"],))]
    return rows


@app.post("/api/topics/{tid}/verify")
def api_verify_topic(tid: int):
    t = workflow.topic_dict(tid)
    if not t:
        raise HTTPException(404, "Topic not found")
    v = workflow.harvester.verify_topic(t)
    v = workflow.harvester.score(v)
    execute("UPDATE topics SET title=?, source=?, source_kind=? WHERE id=?", (v["title"], v.get("source", ""), v.get("source_kind", ""), tid))
    execute("""UPDATE topics SET verification_status=?, verification_note=?, preview_image_url=?, description=?, stars=?,
               why_it_matters=?, facts_json=?, opportunity_score=?, usefulness=?, relevance=?, suggested_format=?,
               suggested_slides=?, verified_date=? WHERE id=?""",
            (v["verification_status"], v.get("verification_note", ""), v.get("preview_image_url", ""), v.get("description", ""),
             v.get("stars", 0), v.get("why_it_matters", ""), json.dumps(v.get("facts", [])), v["opportunity_score"],
             v["usefulness"], v["relevance"], v["suggested_format"], v["suggested_slides"], ts()[:10], tid))
    from research.harvester import priority
    execute("UPDATE topics SET status=? WHERE id=? AND status IN ('NEW','LOW_PRIORITY')", (priority(v), tid))
    log_event("research", f"Re-verified topic #{tid}: {v['verification_status']}", tid)
    t = workflow.topic_dict(tid)
    return {"success": True, "topic": t}


@app.post("/api/topics/{tid}/dismiss")
def api_dismiss_topic(tid: int):
    execute("UPDATE topics SET status='DISMISSED' WHERE id=?", (tid,))
    return {"success": True}


@app.post("/api/research/run")
def api_research_run():
    return start_job("research", workflow.run_research)


@app.post("/api/automation/run-now")
def api_pipeline_run():
    return start_job("pipeline", workflow.run_pipeline)


@app.get("/api/jobs")
def api_jobs(kind: str = "", limit: int = 50):
    if kind:
        return query("SELECT * FROM jobs WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
    return query("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/api/jobs/{jid}")
def api_job(jid: int):
    j = one("SELECT * FROM jobs WHERE id=?", (jid,))
    if not j:
        raise HTTPException(404, "Job not found")
    return j


# ------------------------------------------------------------------ carousels
def _c(cid: int):
    c = workflow.load_carousel(cid)
    if not c:
        raise HTTPException(404, "Carousel not found")
    return c


@app.get("/api/carousels")
def api_carousels(status: str = ""):
    rows = query("SELECT id FROM carousels" + (" WHERE status=?" if status else "") + " ORDER BY id DESC", (status,) if status else ())
    return [workflow.load_carousel(r["id"]) for r in rows]


@app.post("/api/carousels")
async def api_create_carousel(req: Request):
    b = await body(req)
    if b.get("topic_ids"):
        return workflow.create_pack(b["topic_ids"])
    if not b.get("topic_id"):
        raise ValueError("topic_id is required")
    return workflow.create_from_topic(int(b["topic_id"]), b.get("slides"))


@app.get("/api/carousels/{cid}")
def api_carousel(cid: int):
    return _c(cid)


@app.put("/api/carousels/{cid}")
async def api_update_carousel(cid: int, req: Request):
    _c(cid)
    return workflow.update_carousel(cid, await body(req))


@app.post("/api/carousels/{cid}/preview", response_class=HTMLResponse)
async def api_preview_unsaved(cid: int, req: Request):
    """Live preview of unsaved edits (slides + design) without persisting."""
    c = _c(cid)
    b = await body(req)
    if isinstance(b.get("slides"), list):
        c["slide_data"]["slides"] = b["slides"]
    if isinstance(b.get("design"), dict):
        c["design"] = {**c["design"], **b["design"]}
    only = b.get("only")
    return HTMLResponse(workflow.slide_html(c, int(only) if only else None))


@app.get("/api/carousels/{cid}/guide.html", response_class=HTMLResponse)
def api_guide_html(cid: int):
    """The DM guide document (same HTML that is rendered to images and sent in the DM)."""
    return HTMLResponse(workflow.guide_html(_c(cid))[0])


@app.get("/api/carousels/{cid}/slides/{n}.html", response_class=HTMLResponse)
def api_slide_html(cid: int, n: int):
    return HTMLResponse(workflow.slide_html(_c(cid), n))


@app.post("/api/carousels/{cid}/render")
def api_render(cid: int):
    _c(cid)
    return start_job("render", lambda ctx: workflow.render(cid, ctx=ctx), ref_id=cid)


@app.post("/api/carousels/{cid}/regenerate")
async def api_regenerate(cid: int, req: Request):
    b = await body(req)
    return workflow.regenerate(cid, b.get("slide_index"), b.get("slides"))


@app.post("/api/carousels/{cid}/slides/{n}/image")
async def api_slide_image(cid: int, n: int, file: UploadFile = File(...)):
    c = _c(cid)
    slides = c["slide_data"].get("slides", [])
    if not 1 <= n <= len(slides):
        raise ValueError("Slide index out of range")
    ext = (Path(file.filename or "").suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise ValueError("Upload a JPG, PNG, WEBP or GIF image")
    data = await file.read()
    if len(data) > 8_000_000:
        raise ValueError("Image too large (max 8 MB)")
    d = workflow.carousel_dir(cid) / "assets"
    d.mkdir(parents=True, exist_ok=True)
    name = f"slide{n}_{int(time.time())}{ext}"
    (d / name).write_bytes(data)
    slides[n - 1]["image"] = f"/api/media/carousels/{cid}/assets/{name}"
    return workflow.update_carousel(cid, {"slides": slides})


@app.post("/api/carousels/{cid}/submit")
def api_submit(cid: int):
    return workflow.submit(cid)


@app.post("/api/carousels/{cid}/reject")
async def api_reject(cid: int, req: Request):
    return workflow.reject(cid, (await body(req)).get("reason", "") or "No reason given")


@app.post("/api/carousels/{cid}/publish")
async def api_publish(cid: int, req: Request):
    b = await body(req)
    if not b.get("confirm"):
        raise ValueError("Publishing requires explicit confirmation")
    c = _c(cid)
    if c["status"] not in ("PENDING_APPROVAL", "PUBLISH_FAILED"):
        raise ValueError(f"Only posts in the approval queue can be published (status {c['status']})")
    return start_job("publish", lambda ctx: workflow.publish(cid, ctx), ref_id=cid)


@app.get("/api/media/{path:path}")
def api_media(path: str):
    p = (OUTPUT_DIR / path).resolve()
    if not str(p).startswith(str(OUTPUT_DIR.resolve())) or not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/api/preview/{filename}")
def get_preview(filename: str):
    """Legacy: slides from output/current_carousel."""
    return api_media(f"current_carousel/{filename}")


@app.get("/api/creative/options")
def api_creative_options():
    return {"themes": list(creative.THEMES), "fonts": list(creative.FONTS),
            "layouts": ["cover", "cover_type", "point", "quote", "facts", "facts_list", "steps", "image", "cta", "cta_minimal", "single"]}


# ------------------------------------------------------------------ settings
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
VALIDATORS = {
    "publishing_mode": lambda v: v in ("REVIEW", "AUTO"),
    "target_publish_time": lambda v: bool(TIME_RE.match(v)),
    "research_time": lambda v: bool(TIME_RE.match(v)),
    "min_qc_score": lambda v: v.isdigit() and 0 <= int(v) <= 100,
    "max_posts_per_day": lambda v: v.isdigit() and 1 <= int(v) <= 5,
    "max_research_items": lambda v: v.isdigit() and 5 <= int(v) <= 100,
    "auto_categories": lambda v: bool(v) and all(x in CATEGORIES for x in v.split(",")),
    "scheduler_enabled": lambda v: v in ("0", "1"),
    "default_cta_keyword": lambda v: bool(re.match(r"^[A-Z0-9_]{2,20}$", v)),
    "default_hashtags": lambda v: len(v) <= 300 and all(t.startswith("#") for t in v.split()),
    "default_theme": lambda v: v in creative.THEMES,
    "default_accent": lambda v: bool(re.match(r"^#[0-9a-fA-F]{6}$", v)),
    "brand_name": lambda v: 1 <= len(v) <= 40,
    "creator_handle": lambda v: bool(re.match(r"^@[A-Za-z0-9._]{1,30}$", v)),
    "auto_dm": lambda v: v in ("0", "1"),
    "dm_follow_gate": lambda v: v in ("0", "1"),
    "dm_poll_minutes": lambda v: v.isdigit() and 1 <= int(v) <= 60,
    "dm_opener": lambda v: 5 <= len(v) <= 600,
    "dm_not_following": lambda v: 5 <= len(v) <= 600,
}


@app.get("/api/settings")
def api_get_settings():
    return get_settings()


@app.post("/api/settings")
async def api_update_settings(req: Request):
    b = await body(req)
    errors = {}
    for k, v in b.items():
        if k == "confirm_auto":
            continue
        v = str(v).strip()
        if k not in VALIDATORS:
            errors[k] = "Unknown setting"
        elif not VALIDATORS[k](v):
            errors[k] = "Invalid value"
        elif k == "publishing_mode" and v == "AUTO" and not b.get("confirm_auto"):
            errors[k] = "Auto Mode requires explicit confirmation"
    if errors:
        return JSONResponse(status_code=400, content={"success": False, "error": "Validation failed", "fields": errors})
    for k, v in b.items():
        if k != "confirm_auto":
            set_setting(k, str(v).strip())
    log_event("settings", "Updated " + ", ".join(k for k in b if k != "confirm_auto"))
    return {"success": True, "settings": get_settings()}


@app.get("/api/system")
def api_system():
    """Non-secret runtime facts for Settings (never returns credential values)."""
    gh = None
    try:
        import requests as rq
        r = rq.get("https://api.github.com/rate_limit", headers=workflow.harvester.gh_headers, timeout=8)
        gh = r.json().get("resources", {}).get("search") if r.ok else None
    except Exception:
        pass
    return {"browser": creative.find_browser(), "github_token": bool(os.getenv("GITHUB_TOKEN")), "github_search_limit": gh,
            "llm_configured": bool(os.getenv("ANTHROPIC_API_KEY")), "db": str(workflow.OUTPUT_DIR.parent / "data"),
            "account_id": meta.ig_user_id, "meta_app_id": bool(meta.app_id), "meta_app_secret": bool(meta.app_secret)}


# ------------------------------------------------------------------ meta
@app.get("/api/meta/diagnostics")
def api_meta_diagnostics():
    d = dict(meta_status(force=True))
    d.pop("app_id_configured", None)
    return d


@app.post("/api/meta/token")
async def api_meta_token(req: Request):
    """Exchange a short-lived token for a 60-day token and store it in .env — only if it can read the configured account."""
    token = str((await body(req)).get("token", "")).strip()
    if len(token) < 50:
        raise ValueError("Paste a Graph API user access token")
    exchanged, expires_in = False, None
    if meta.app_id and meta.app_secret:
        ex = meta.exchange_for_long_lived_token(token)
        if not ex.get("success"):
            raise ValueError(f"Token exchange failed: {str(ex.get('error'))[:200]}")
        token, expires_in, exchanged = ex["access_token"], ex.get("expires_in"), True
    new = token
    import requests as rq
    r = rq.get(f"https://graph.facebook.com/v22.0/{meta.ig_user_id}", params={"fields": "username", "access_token": new}, timeout=15)
    if r.status_code != 200:
        raise ValueError("This token cannot access the configured Instagram account — not saved.")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    lines = [ln for ln in lines if not ln.startswith("META_ACCESS_TOKEN=")] + [f"META_ACCESS_TOKEN={new}"]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["META_ACCESS_TOKEN"] = new
    responder.reload()
    log_event("settings", f"Meta token renewed for @{r.json().get('username')}")
    d = meta_status(force=True)
    return {"success": True, "username": r.json().get("username"), "expires_in": expires_in, "exchanged": exchanged,
            "expires_at": (d.get("token") or {}).get("expires_at"), "token_valid": d.get("token_valid")}


@app.get("/api/meta/discover")
def api_meta_discover():
    return meta.discover_instagram_account_id()


_analytics_cache: Dict[int, Any] = {}


@app.get("/api/analytics")
def api_analytics(days: int = 30, refresh: bool = False):
    days = max(1, min(days, 30))
    hit = _analytics_cache.get(days)
    if hit and not refresh and time.time() - hit[0] < 600:
        return hit[1]
    m = meta_status()
    if not m.get("token_valid"):
        return {"success": False, "error": m.get("error") or "Instagram not connected", "connected": False}
    ins = meta.get_account_insights(days)
    media = meta.get_recent_media(25)
    local = {r["mid"]: r for r in query("""SELECT COALESCE(NULLIF(c.ig_media_id,''), c.metricool_post_id) mid, c.id, c.post_format,
                                           c.slide_count, t.category FROM carousels c LEFT JOIN topics t ON t.id=c.topic_id
                                           WHERE c.status='PUBLISHED'""")}
    for x in media.get("media", []):
        l = local.get(x["id"])
        x["category"] = (l or {}).get("category") or "Not created here"
        x["carousel_id"] = (l or {}).get("id")
    out = {"success": True, "connected": True, "account": m.get("account"), "days": days,
           "series": ins.get("series", {}), "totals": ins.get("totals", {}),
           "errors": ins.get("errors", []) + ([media["error"]] if not media.get("success") else []) + ([ins["error"]] if not ins.get("success") else []),
           "media": media.get("media", [])}
    _analytics_cache[days] = (time.time(), out)
    return out


@app.get("/api/meta/insights")
def api_meta_insights():
    return meta.get_account_insights()


# ------------------------------------------------------------------ campaigns
CAMPAIGN_FIELDS = ["name", "keyword", "media_id", "carousel_id", "private_reply", "follow_gate", "follow_gate_message",
                   "resource_pack", "public_reply_enabled", "public_reply_text", "active"]


def _campaign_clean(b: Dict[str, Any]) -> Dict[str, Any]:
    c = {k: b.get(k) for k in CAMPAIGN_FIELDS if k in b}
    if "keyword" in c:
        c["keyword"] = re.sub(r"[^A-Za-z0-9_]", "", str(c["keyword"])).upper()
        if not 2 <= len(c["keyword"]) <= 20:
            raise ValueError("Keyword must be 2–20 letters/digits")
    if "name" in c and not str(c["name"]).strip():
        raise ValueError("Campaign name is required")
    if c.get("media_id") and not re.match(r"^\d{5,30}$", str(c["media_id"])):
        raise ValueError("Media id must be the numeric Instagram media id")
    if c.get("carousel_id"):
        car = one("SELECT ig_media_id, metricool_post_id, status FROM carousels WHERE id=?", (int(c["carousel_id"]),))
        if not car or car["status"] != "PUBLISHED":
            raise ValueError("Linked post must be published")
        c["media_id"] = car["ig_media_id"] or car["metricool_post_id"]
    for k in ("follow_gate", "public_reply_enabled", "active"):
        if k in c:
            c[k] = 1 if c[k] in (1, True, "1", "true") else 0
    for k in ("private_reply", "follow_gate_message", "resource_pack", "public_reply_text"):
        if k in c:
            c[k] = str(c[k] or "")[:1000]
    return c


def _campaign_stats(cid: int) -> Dict[str, int]:
    return {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM dm_deliveries WHERE campaign_id=? GROUP BY status", (cid,))}


@app.get("/api/campaigns")
def api_campaigns():
    rows = query("SELECT * FROM campaigns ORDER BY id DESC")
    for r in rows:
        r["stats"] = _campaign_stats(r["id"])
    return rows


@app.post("/api/campaigns")
async def api_create_campaign(req: Request):
    c = _campaign_clean(await body(req))
    if not c.get("name") or not c.get("keyword"):
        raise ValueError("Name and keyword are required")
    if c.get("active") and not c.get("media_id"):
        raise ValueError("Link a published post before activating")
    cols = ",".join(c)
    cid = execute(f"INSERT INTO campaigns ({cols}, created_at, updated_at) VALUES ({','.join('?' * len(c))}, ?, ?)", (*c.values(), ts(), ts()))
    log_event("dm", f"Campaign “{c['name']}” created", cid)
    return one("SELECT * FROM campaigns WHERE id=?", (cid,))


@app.put("/api/campaigns/{cid}")
async def api_update_campaign(cid: int, req: Request):
    cur = one("SELECT * FROM campaigns WHERE id=?", (cid,))
    if not cur:
        raise HTTPException(404, "Campaign not found")
    c = _campaign_clean(await body(req))
    if (c.get("active", cur["active"])) and not c.get("media_id", cur["media_id"]):
        raise ValueError("Link a published post before activating")
    if c:
        execute(f"UPDATE campaigns SET {', '.join(k + '=?' for k in c)}, updated_at=? WHERE id=?", (*c.values(), ts(), cid))
    return one("SELECT * FROM campaigns WHERE id=?", (cid,))


@app.get("/api/campaigns/{cid}/deliveries")
def api_deliveries(cid: int):
    return query("SELECT * FROM dm_deliveries WHERE campaign_id=? ORDER BY id DESC LIMIT 200", (cid,))


@app.post("/api/campaigns/{cid}/scan")
async def api_scan(cid: int, req: Request):
    b = await body(req)
    camp = one("SELECT * FROM campaigns WHERE id=?", (cid,))
    if not camp:
        raise HTTPException(404, "Campaign not found")
    live = bool(b.get("live"))
    if live and not (camp["active"] and b.get("confirm")):
        raise ValueError("Live sending needs an active campaign and explicit confirmation")
    responder.reload()

    def run(ctx):
        ctx.stage("Engagement: scanning comments", 20)
        return responder.scan_campaign(camp, dry_run=not live, log=ctx.log)
    return start_job("dm_scan", run, ref_id=cid, background=not b.get("wait"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("CMS_HOST", "127.0.0.1"), port=int(os.getenv("CMS_PORT", "8000")))

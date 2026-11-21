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

from config import CATEGORIES, ON_VERCEL, OUTPUT_DIR  # noqa: E402
from db.migrate_v2 import migrate  # noqa: E402

SETUP_ERROR = ""
try:
    from store import IS_PG as _IS_PG
    if os.getenv("VERCEL") and not _IS_PG:
        raise RuntimeError("No database connected. In Vercel: Storage → Create/Connect a Postgres (Neon) database, then redeploy.")
    migrate()
except Exception as _e:  # surfaced by the auth middleware instead of a blank 500
    SETUP_ERROR = str(_e)

import workflow  # noqa: E402
from automation.comment_responder import CommentResponder  # noqa: E402
from generator import creative  # noqa: E402
from scheduler import daily_runner  # noqa: E402
import media  # noqa: E402
import qstash_client  # noqa: E402
from scheduler import jobs as sched_jobs, qstash_schedules  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from automation import webhook_inbox  # noqa: E402
from store import (execute, get_secret, get_settings, log_event, now_ist, one, query, recover_stale_jobs,  # noqa: E402
                   set_secret, set_setting, start_job, ts)

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="SONU AI LAB")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
responder = CommentResponder()
meta = workflow.meta


# ------------------------------------------------------------------ login (required on Vercel)
import hashlib  # noqa: E402
import hmac  # noqa: E402

APP_PASSWORD = os.getenv("APP_PASSWORD", "")
OPEN_PATHS = ("/api/login", "/api/logout", "/api/health", "/api/webhooks/", "/api/cron/", "/api/queue/", "/static/")  # webhooks/queue/cron verify their own signatures
SESSION_DAYS = 30


def _session_key() -> bytes:
    return hashlib.sha256(f"session:{os.getenv('APP_SECRET') or APP_PASSWORD}".encode()).digest()


def _make_session() -> str:
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    return exp + "." + hmac.new(_session_key(), exp.encode(), hashlib.sha256).hexdigest()


def _valid_session(v: str) -> bool:
    try:
        exp, sig = v.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, hmac.new(_session_key(), exp.encode(), hashlib.sha256).hexdigest())
    except Exception:
        return False


_setup_tried = [0.0]


def _retry_setup() -> bool:
    """A failed start (e.g. DB not ready yet) is retried at most every 10 s instead of being remembered forever."""
    global SETUP_ERROR
    if time.time() - _setup_tried[0] < 10:
        return False
    _setup_tried[0] = time.time()
    try:
        from store import IS_PG as _pg
        if os.getenv("VERCEL") and not _pg:
            return False
        migrate()
        SETUP_ERROR = ""
        return True
    except Exception as e:
        SETUP_ERROR = str(e)
        return False


@app.middleware("http")
async def _auth(request: Request, call_next):
    path = request.url.path
    if SETUP_ERROR and path.startswith("/api/") and not _retry_setup():
        return JSONResponse(status_code=503, content={"error": f"Setup needed: {SETUP_ERROR}"})
    if path == "/" or path.startswith(OPEN_PATHS):
        return await call_next(request)
    if not APP_PASSWORD:
        if ON_VERCEL:  # never run the cloud app without a login
            return JSONResponse(status_code=503, content={"error": "Set APP_PASSWORD in the Vercel project environment variables."})
        return await call_next(request)
    if not _valid_session(request.cookies.get("sal_session", "")):
        return JSONResponse(status_code=401, content={"error": "login required"})
    return await call_next(request)


@app.post("/api/login")
async def api_login(req: Request):
    pw = str((await body(req)).get("password", ""))
    if not APP_PASSWORD or not hmac.compare_digest(pw.encode(), APP_PASSWORD.encode()):
        time.sleep(1)  # slow down guessing
        return JSONResponse(status_code=401, content={"error": "Wrong password"})
    r = JSONResponse({"success": True})
    r.set_cookie("sal_session", _make_session(), max_age=SESSION_DAYS * 86400, httponly=True,
                 secure=req.url.scheme == "https" or ON_VERCEL, samesite="lax")
    return r


@app.post("/api/logout")
def api_logout():
    r = JSONResponse({"success": True})
    r.delete_cookie("sal_session")
    return r


@app.get("/api/health")
def api_health():
    return {"ok": True, "cloud": ON_VERCEL, "login": bool(APP_PASSWORD)}


@app.middleware("http")
async def _revalidate_static(request: Request, call_next):
    """Static assets revalidate via ETag on every load, so UI updates are never masked by heuristic caching."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.on_event("startup")
def _startup():
    if ON_VERCEL:
        return  # Vercel: Cron + webhooks replace the scheduler thread; jobs run inline
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
    week = query("SELECT status FROM jobs WHERE started_at >= ?", ((now_ist() - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d"),))
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
    limit = 3_000_000 if ON_VERCEL else 8_000_000  # Vercel request bodies max out around 4.5 MB
    if len(data) > limit:
        raise ValueError(f"Image too large (max {limit // 1_000_000} MB)")
    ctype = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
    slides[n - 1]["image"] = media.put(f"carousels/{cid}/assets/slide{n}_{int(time.time())}{ext}", data, ctype)
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
    if c["status"] not in ("PENDING_APPROVAL", "PUBLISH_FAILED", "PUBLISHING"):  # PUBLISHING: publish() reconciles or refuses
        raise ValueError(f"Only posts in the approval queue can be published (status {c['status']})")
    recover_stale_jobs(15)
    return start_job("publish", lambda ctx: workflow.publish(cid, ctx), ref_id=cid)


@app.post("/api/carousels/{cid}/reconcile")
def api_reconcile(cid: int):
    """'Check status' for a post stuck in Publishing: asks Meta whether it went live. Never publishes."""
    _c(cid)
    recover_stale_jobs(15)
    res = workflow.recover_stuck_publishing(cid)
    note = None if res else f"Still within the {workflow.STUCK_AFTER_MIN}-minute window of an active publish. Check again shortly."
    return {"results": res, "note": note, "carousel": workflow.load_carousel(cid)}


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
    "generate_time": lambda v: v == "" or bool(TIME_RE.match(v)),   # "" = automatic (45 min before publishing)
    "analytics_time": lambda v: bool(TIME_RE.match(v)),
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
        elif k == "publishing_mode" and v == "AUTO" and not b.get("confirm_auto") and get_settings().get("publishing_mode") != "AUTO":
            errors[k] = "Auto Mode requires explicit confirmation"
    if errors:
        return JSONResponse(status_code=400, content={"success": False, "error": "Validation failed", "fields": errors})
    for k, v in b.items():
        if k != "confirm_auto":
            set_setting(k, str(v).strip())
    log_event("settings", "Updated " + ", ".join(k for k in b if k != "confirm_auto"))
    out = {"success": True, "settings": get_settings()}
    if SCHEDULE_KEYS & set(b) and qstash_client.configured():  # times changed → replace the QStash schedules
        out["schedule_sync"] = qstash_schedules.sync()
    return out


SCHEDULE_KEYS = {"research_time", "generate_time", "target_publish_time", "analytics_time", "scheduler_enabled", "timezone"}


@app.get("/api/scheduler/status")
def api_scheduler_status():
    s = get_settings()
    return {"qstash_configured": qstash_client.configured(), "can_verify": qstash_client.can_verify(),
            "times": workflow.schedule_times(s), "timezone": s.get("timezone") or "Asia/Kolkata", "next_runs": sched_jobs.next_runs(),
            "wanted": {k: {"path": v[0], "cron": v[1]} for k, v in qstash_schedules.desired(s).items()},
            "last_sync_at": s.get("qstash_sync_at", ""), "last_sync_error": s.get("qstash_sync_error", ""),
            "due_post": workflow.due_post()}


# ------------------------------------------------------------------ Automation overview (Phase 6): every value from the DB
SYSTEM_JOBS = {"research": ["research"], "generate": ["generate", "pipeline"], "publishing": ["publish", "publish_due"], "analytics": ["analytics"]}
SYSTEM_NEXT = {"research": "research", "generate": "generate", "publishing": "publish", "analytics": "analytics"}
RUNNABLE = {"research", "generate", "publish_due", "analytics", "maintenance"}


def _job_system(kinds, next_at, enabled):
    marks = ",".join("?" * len(kinds))
    since = (now_ist() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    last = one(f"SELECT id, kind, trigger, status, stage, progress, started_at, finished_at, error FROM jobs WHERE kind IN ({marks}) ORDER BY id DESC LIMIT 1", kinds)
    counts = {r["status"]: r["n"] for r in query(f"SELECT status, COUNT(*) n FROM jobs WHERE kind IN ({marks}) AND started_at >= ? GROUP BY status", (*kinds, since))}
    err = one(f"SELECT id, error, finished_at FROM jobs WHERE kind IN ({marks}) AND status='FAILED' ORDER BY id DESC LIMIT 1", kinds)
    running = one(f"SELECT id, stage, progress FROM jobs WHERE kind IN ({marks}) AND status='RUNNING' ORDER BY id DESC LIMIT 1", kinds)
    status = "RUNNING" if running else ("NEVER" if not last else ("FAILED" if last["status"] == "FAILED" else "OK"))
    return {"status": status, "last": last, "running": running, "success_7d": counts.get("SUCCESS", 0), "failed_7d": counts.get("FAILED", 0),
            "latest_error": err, "next_at": next_at if enabled else None}


@app.get("/api/automation/overview")
def api_automation_overview():
    s = get_settings()
    enabled = s.get("scheduler_enabled", "1") == "1"
    nxt = sched_jobs.next_runs()
    systems = {k: _job_system(v, nxt.get(SYSTEM_NEXT[k]), enabled) for k, v in SYSTEM_JOBS.items()}
    systems["publishing"]["posts"] = {
        "failed": one("SELECT COUNT(*) n FROM carousels WHERE status='PUBLISH_FAILED'")["n"],
        "in_progress": one("SELECT COUNT(*) n FROM carousels WHERE status='PUBLISHING'")["n"],
        "scheduled": one("SELECT COUNT(*) n FROM carousels WHERE status='PENDING_APPROVAL' AND approved_at!='' AND approved_at IS NOT NULL AND scheduled_for!=''")["n"],
        "next_scheduled": one("SELECT id, scheduled_for FROM carousels WHERE status='PENDING_APPROVAL' AND approved_at!='' AND approved_at IS NOT NULL AND scheduled_for!='' ORDER BY scheduled_for LIMIT 1"),
    }
    since_utc = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM webhook_events WHERE kind='comment' AND received_at >= ? GROUP BY status", (since_utc,))}
    ev_err = one("SELECT id, error, received_at FROM webhook_events WHERE status='FAILED' ORDER BY id DESC LIMIT 1")
    last_ev = one("SELECT received_at FROM webhook_events WHERE kind='comment' ORDER BY id DESC LIMIT 1")
    systems["comments"] = {"status": "FAILED" if ev.get("FAILED") else ("OK" if last_ev else "NEVER"),
                           "last_received_at": (last_ev or {}).get("received_at"), "counts_7d": ev,
                           "success_7d": ev.get("PROCESSED", 0) + ev.get("IGNORED", 0), "failed_7d": ev.get("FAILED", 0), "latest_error": ev_err,
                           "pending": ev.get("PENDING", 0) + ev.get("QUEUED", 0)}
    dm = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM dm_deliveries GROUP BY status")}
    dm_err = one("SELECT id, campaign_id, error, updated_at FROM dm_deliveries WHERE status IN ('FAILED','UNCERTAIN') ORDER BY id DESC LIMIT 1")
    last_dm = one("SELECT sent_at FROM dm_deliveries WHERE sent_at!='' AND sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 1")
    systems["dm"] = {"status": "FAILED" if dm_err and dm.get("FAILED", 0) + dm.get("UNCERTAIN", 0) else ("OK" if last_dm else "NEVER"),
                     "last_sent_at": (last_dm or {}).get("sent_at"), "counts": dm,
                     "success_7d": one("SELECT COUNT(*) n FROM dm_deliveries WHERE sent_at >= ?", (since_utc,))["n"],
                     "failed_7d": dm.get("FAILED", 0) + dm.get("UNCERTAIN", 0), "latest_error": dm_err}
    wh_counts = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM webhook_events GROUP BY status")}
    audit = s.get("meta_audit_json", "")
    try:
        audit = json.loads(audit) if audit else None
    except ValueError:
        audit = None
    health = {
        "verified_at": s.get("webhook_verified_at", ""), "app_secret_configured": bool(_meta_app_secret()),
        "callback_url": f"{media._base()}/api/webhooks/instagram" if ON_VERCEL else "", "last_received_at": s.get("webhook_last_received_at", ""),
        "last_processed_at": (one("SELECT processed_at FROM webhook_events WHERE processed_at!='' ORDER BY processed_at DESC LIMIT 1") or {}).get("processed_at", ""),
        "last_dm_at": (last_dm or {}).get("sent_at", ""), "failed_dm_count": dm.get("FAILED", 0) + dm.get("UNCERTAIN", 0),
        "events": wh_counts,
        "qstash": {"configured": qstash_client.configured(), "can_verify": qstash_client.can_verify(), "last_sync_at": s.get("qstash_sync_at", ""),
                   "sync_error": s.get("qstash_sync_error", ""), "schedules": len(json.loads(s.get("qstash_schedules") or "[]"))},
        "subscription": {"checked_at": s.get("meta_audit_at", ""), "comments": (audit or {}).get("webhook_fields", {}).get("comments"),
                         "messages": (audit or {}).get("webhook_fields", {}).get("messages"), "page_subscribed": (audit or {}).get("page_subscribed")} if audit
                        else {"checked_at": "", "note": "Not checked yet: run the Meta configuration check"},
    }
    return {"enabled": enabled, "mode": s.get("publishing_mode", "REVIEW"), "times": workflow.schedule_times(s), "systems": systems, "webhook": health}


@app.post("/api/meta/audit")
def api_meta_audit():
    """Read-only Meta configuration check (GET requests only). Result is stored for the Webhook health panel; no tokens in it."""
    import meta_audit
    meta.reload()
    res = meta_audit.run()
    set_setting("meta_audit_json", json.dumps(res)[:20000])
    set_setting("meta_audit_at", res["checked_at"])
    return res


@app.get("/api/meta/audit")
def api_meta_audit_last():
    raw = get_settings().get("meta_audit_json", "")
    return json.loads(raw) if raw else {"checked_at": "", "note": "Not checked yet"}


@app.post("/api/automation/run/{kind}")
async def api_automation_run(kind: str, req: Request):
    """Dashboard 'Run now'. Uses the same DB lease as scheduled runs, so it never overlaps one. Publishing needs confirm."""
    if kind not in RUNNABLE:
        raise HTTPException(404, "Unknown job")
    if kind == "publish_due" and not (await body(req)).get("confirm"):
        raise ValueError("Publishing due posts needs explicit confirmation")
    fn = sched_jobs.JOBS[kind]["fn"]

    def locked(ctx):
        holder = sched_jobs.acquire(kind)
        if not holder:
            return {"success": False, "error": f"A {kind} run is already in progress (scheduled or manual)"}
        try:
            return fn(ctx)
        finally:
            sched_jobs.release(kind, holder)
    return start_job(kind, locked, trigger="manual")


@app.post("/api/scheduler/sync")
def api_scheduler_sync():
    return qstash_schedules.sync()


@app.post("/api/queue/job/{kind}")
async def api_queue_job(kind: str, request: Request):
    """QStash schedule callback. Signature must be valid for this exact URL; slot + lease make redelivery harmless."""
    raw = await request.body()
    ok, why = qstash_client.verify(request.headers.get("upstash-signature", ""), raw, qstash_client.destination(f"/api/queue/job/{kind}"))
    if not ok:
        return JSONResponse(status_code=401, content={"error": why})
    if kind == "tick":  # maintenance + any post scheduled for a custom time
        c1, r1 = sched_jobs.run("maintenance", trigger="qstash")
        c2, r2 = sched_jobs.run("publish_due", trigger="qstash") if workflow.due_post() else (200, {"skipped": "nothing due"})
        return JSONResponse(status_code=max(c1, c2), content={"maintenance": r1, "publish_due": r2})
    code, res = sched_jobs.run(kind, trigger="qstash")
    return JSONResponse(status_code=code, content=res)


@app.post("/api/carousels/{cid}/schedule")
async def api_schedule_post(cid: int, req: Request):
    """Approve + schedule. `at` is local dashboard time (Asia/Kolkata) 'YYYY-MM-DDTHH:MM'; stored as UTC."""
    b = await body(req)
    if not b.get("confirm"):
        raise ValueError("Scheduling a post approves it for publishing; confirm is required")
    try:
        when = workflow.ist_to_utc(str(b.get("at", "")))
    except ValueError:
        raise ValueError("Pick a date and time")
    now = datetime.now(timezone.utc)
    when_dt = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if when_dt < now - timedelta(minutes=1) or when_dt > now + timedelta(days=60):
        raise ValueError("Choose a time between now and 60 days ahead")
    return workflow.schedule_post(cid, when)


@app.delete("/api/carousels/{cid}/schedule")
def api_unschedule_post(cid: int):
    return workflow.unschedule_post(cid)


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
    return {"browser": "Serverless Chromium (api/render.js) + Vercel Blob" if ON_VERCEL else creative.find_browser(), "cloud": ON_VERCEL,
            "webhook_url": f"{media._base()}/api/webhooks/instagram" if ON_VERCEL else "", "webhook_verify_token": webhook_token(), "github_token": bool(os.getenv("GITHUB_TOKEN")), "github_search_limit": gh,
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
    """Exchange (when the app secret is set) and save a token — only if it can read the configured Instagram account."""
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
    set_secret("meta_access_token", new)  # database, so it also works on Vercel (env vars are read-only there)
    meta.reload()
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
                   "resource_pack", "public_reply_enabled", "public_reply_text", "active", "keywords", "guide_url"]


def _campaign_clean(b: Dict[str, Any]) -> Dict[str, Any]:
    c = {k: b.get(k) for k in CAMPAIGN_FIELDS if k in b}
    if "keyword" in c:
        c["keyword"] = re.sub(r"[^A-Za-z0-9_]", "", str(c["keyword"])).upper()
        if not 2 <= len(c["keyword"]) <= 20:
            raise ValueError("Keyword must be 2–20 letters/digits")
    if "keywords" in c:  # extra trigger words; matching is case-insensitive, whole word
        extra = [re.sub(r"[^A-Za-z0-9_]", "", w).upper() for w in re.split(r"[,\s]+", str(c["keywords"] or ""))]
        extra = list(dict.fromkeys(w for w in extra if w))
        if len(extra) > 10 or any(not 2 <= len(w) <= 20 for w in extra):
            raise ValueError("Up to 10 extra keywords, each 2–20 letters/digits")
        c["keywords"] = ",".join(extra)
    if "guide_url" in c:
        c["guide_url"] = str(c["guide_url"] or "").strip()
        if c["guide_url"] and not re.match(r"^https://\S{4,500}$", c["guide_url"]):
            raise ValueError("Guide link must be a full https:// URL")
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


@app.get("/api/deliveries/{did}/log")
def api_delivery_log(did: int):
    return query("SELECT * FROM dm_delivery_log WHERE delivery_id=? ORDER BY id", (did,))


@app.post("/api/deliveries/{did}/retry")
async def api_delivery_retry(did: int, req: Request):
    """Safe retry: FAILED only. UNCERTAIN (Meta may have sent it) needs confirm_uncertain=true because it can double-message."""
    from automation import dm_engine
    return dm_engine.retry_delivery(did, force_uncertain=bool((await body(req)).get("confirm_uncertain")))


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


# ------------------------------------------------------------------ Vercel Cron (daily research / build)
def _cron_ok(req: Request) -> bool:
    secret = os.getenv("CRON_SECRET", "")
    return bool(secret) and hmac.compare_digest(req.headers.get("authorization", ""), f"Bearer {secret}")


@app.get("/api/cron/{kind}")
def api_cron(kind: str, request: Request):
    if not _cron_ok(request):
        return JSONResponse(status_code=401, content={"error": "Set CRON_SECRET in Vercel; cron requests must carry it"})
    if kind == "tick":  # called every few minutes; runs research/pipeline at the times set on the Automation page
        return {"started": daily_runner.tick()}
    if kind == "research":
        return start_job("research", workflow.run_research, trigger="cron", background=False)
    if kind == "pipeline":
        return start_job("pipeline", workflow.run_pipeline, trigger="cron", background=False)
    if kind == "maintenance":  # daily Vercel safety net (vercel.json): recovery only, never content
        code, res = sched_jobs.run("maintenance", trigger="cron")
        return JSONResponse(status_code=code, content=res)
    if kind == "dm":  # optional: call every few minutes from an external cron as a backup to webhooks
        set_setting("dm_last_poll", "")
        return daily_runner.poll_dms()
    raise HTTPException(404, "Unknown cron")


# ------------------------------------------------------------------ Instagram webhooks (real-time comment-to-DM)
def webhook_token() -> str:
    t = get_secret("webhook_verify_token")
    if not t:
        t = hashlib.sha256(f"wh:{time.time()}:{os.urandom(8).hex()}".encode()).hexdigest()[:32]
        set_secret("webhook_verify_token", t)
    return t


@app.get("/api/webhooks/instagram")
def api_webhook_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", ""), webhook_token()):
        set_setting("webhook_verified_at", webhook_inbox.utc_now())  # Meta (or you) completed the subscription handshake
        return HTMLResponse(q.get("hub.challenge", ""))
    return JSONResponse(status_code=403, content={"error": "verify token mismatch"})


def _meta_app_secret() -> str:
    return os.getenv("META_APP_SECRET", "") or meta.app_secret or ""


@app.post("/api/webhooks/instagram")
async def api_webhook(request: Request):
    """Verify → store → enqueue → 200. No Graph API calls here: Meta needs a fast answer, and the work runs from the queue."""
    raw = await request.body()
    secret = _meta_app_secret()
    if not secret:  # without the app secret nobody can tell Meta's events from forged ones
        log_event("webhook", "Rejected a webhook: META_APP_SECRET is not configured")
        return JSONResponse(status_code=503, content={"error": "META_APP_SECRET not configured"})
    sig = request.headers.get("x-hub-signature-256", "")
    good = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(sig, good):
        return JSONResponse(status_code=403, content={"error": "missing or invalid X-Hub-Signature-256"})
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    set_setting("webhook_last_received_at", webhook_inbox.utc_now())
    new_ids = webhook_inbox.store(webhook_inbox.parse(data))
    out = webhook_inbox.dispatch(new_ids)
    return {"ok": True, "stored": len(new_ids), **out}


@app.post("/api/queue/webhook-event")
async def api_queue_webhook_event(request: Request):
    """QStash callback. Only QStash-signed requests for this exact URL are accepted; processing is idempotent."""
    raw = await request.body()
    ok, why = qstash_client.verify(request.headers.get("upstash-signature", ""), raw, qstash_client.destination(webhook_inbox.PROCESS_PATH))
    if not ok:
        return JSONResponse(status_code=401, content={"error": why})
    try:
        event_id = int(json.loads(raw or b"{}").get("event_id"))
    except (ValueError, TypeError, AttributeError):
        return JSONResponse(status_code=400, content={"error": "event_id required"})
    code, res = webhook_inbox.process_event(event_id)
    return JSONResponse(status_code=code, content=res)


@app.get("/api/inbox/events")
def api_inbox_events(limit: int = 50, status: str = ""):
    rows = query(f"SELECT id, event_key, kind, media_id, sender_username, text, status, attempts, received_at, queued_at, processed_at, error, result_json "
                 f"FROM webhook_events {'WHERE status=?' if status else ''} ORDER BY id DESC LIMIT ?",
                 ((status, min(limit, 200)) if status else (min(limit, 200),)))
    counts = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM webhook_events GROUP BY status")}
    return {"events": rows, "counts": counts, "qstash": {"configured": qstash_client.configured(), "can_verify": qstash_client.can_verify()},
            "app_secret_configured": bool(_meta_app_secret()), "last_received_at": get_settings().get("webhook_last_received_at", "")}


@app.post("/api/inbox/sweep")
def api_inbox_sweep():
    return webhook_inbox.sweep()


@app.post("/api/inbox/events/{event_id}/retry")
def api_inbox_retry(event_id: int):
    return webhook_inbox.retry_failed(event_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("CMS_HOST", "127.0.0.1"), port=int(os.getenv("CMS_PORT", "8000")))

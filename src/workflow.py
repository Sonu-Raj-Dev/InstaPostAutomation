"""Content workflow: topic → carousel draft → render → QC → approval → publish. Used by API + scheduler."""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CATEGORIES, OUTPUT_DIR
from generator import creative
from meta_graph_client import POLL_INTERVAL_S, MetaGraphClient, check_image_url, format_error
from qc.evaluator import QualityControlEvaluator
from research.harvester import ResearchHarvester, recommend_format
from store import execute, get_setting, get_settings, log_event, now_ist, one, query, ts, update, utc_now
import media
from config import ON_VERCEL

meta = MetaGraphClient()
harvester = ResearchHarvester()
EDITABLE = {"headline", "caption", "hashtags", "cta_keyword", "resource_pack"}
STATUSES = {"DRAFT", "PENDING_APPROVAL", "REJECTED", "PUBLISHING", "PUBLISHED", "PUBLISH_FAILED"}


def carousel_dir(cid: int) -> Path:
    return OUTPUT_DIR / "carousels" / str(cid)


def topic_dict(tid: Optional[int]) -> Dict[str, Any]:
    t = one("SELECT * FROM topics WHERE id=?", (tid,)) if tid else None
    if t:
        t["facts"] = json.loads(t.get("facts_json") or "[]")
    return t or {}


def load_carousel(cid: int) -> Optional[Dict[str, Any]]:
    c = one("SELECT * FROM carousels WHERE id=?", (cid,))
    if not c:
        return None
    c["slide_data"] = json.loads(c.get("slide_data_json") or "{}") or {}
    c["design"] = {**creative.DEFAULT_DESIGN, **json.loads(c.get("design_json") or "{}")}
    c["qc"] = json.loads(c.get("qc_json") or "{}")
    c["topic"] = topic_dict(c.get("topic_id"))
    c["pack_topics"] = [topic_dict(t) for t in c["slide_data"].get("pack", [])]
    slides = c["slide_data"].get("slides", [])
    d = carousel_dir(cid)
    c["rendered"] = json.loads(c.get("rendered_json") or "[]")
    c["guide"] = json.loads(c.get("guide_json") or "[]")
    if not c["rendered"] and not ON_VERCEL and d.exists():  # posts rendered before URLs were stored
        c["guide"] = [f"/api/media/carousels/{cid}/{p.name}" for p in sorted(d.glob("guide_*.jpg"))]
        c["rendered"] = [f"/api/media/carousels/{cid}/slide_{i:02d}.jpg" for i in range(1, len(slides) + 1)
                         if (d / f"slide_{i:02d}.jpg").exists()]
    c["render_stale"] = not c["rendered"] or len(c["rendered"]) != len(slides) or (c.get("rendered_at") or "") < (c.get("updated_at") or "")
    c["legacy"] = not slides  # rows created before v3 have no slide data
    return c


def _qc(c: Dict[str, Any]) -> Dict[str, Any]:
    published = [r["headline"] for r in query("SELECT headline FROM carousels WHERE status='PUBLISHED' AND id!=?", (c.get("id") or 0,))]
    return QualityControlEvaluator(int(get_setting("min_qc_score", "85"))).evaluate(c, c.get("topic"), published)


def _persist(cid: int, c: Dict[str, Any]):
    q = _qc(c)
    execute("""UPDATE carousels SET headline=?, caption=?, hashtags=?, cta_keyword=?, resource_pack=?, slide_data_json=?,
               design_json=?, slide_count=?, post_format=?, quality_score=?, qc_json=?, updated_at=? WHERE id=?""",
            (c["headline"], c["caption"], c.get("hashtags", ""), c.get("cta_keyword", ""), c.get("resource_pack", ""),
             json.dumps(c["slide_data"]), json.dumps(c["design"]), len(c["slide_data"].get("slides", [])),
             c.get("post_format", "CAROUSEL"), q["score"], json.dumps(q), ts(), cid))


def create_from_topic(topic_id: int, slides: Optional[int] = None) -> Dict[str, Any]:
    t = topic_dict(topic_id)
    if not t:
        raise ValueError("Topic not found")
    s = get_settings()
    rec = recommend_format(t)
    n = max(1, min(10, int(slides or rec["slides"])))
    kw = s.get("default_cta_keyword", "AGENT")
    readme = creative.fetch_readme(t.get("url", ""))
    install = readme["install"]
    built = creative.build_slides_v2(t, n, readme, kw)
    fmt = "SINGLE" if len(built) == 1 else ("REEL" if rec["format"] == "REEL" else "CAROUSEL")
    c = {
        "headline": creative.display_title(t) if t.get("source_kind") != "hn" else t["title"],
        "caption": creative.build_caption(t, kw), "hashtags": creative.build_hashtags(t, s.get("default_hashtags", "")),
        "cta_keyword": kw, "resource_pack": creative.dm_message([{"topic": t, "readme": readme}]),
        "slide_data": {"slides": built, "install": install, "readme": readme, "recommendation": rec, "requested": n},
        "design": {**creative.DEFAULT_DESIGN, "theme": s.get("default_theme", "studio"), "accent": s.get("default_accent", "#4C7DFF")},
        "post_format": fmt, "topic": t,
    }
    cid = execute("INSERT INTO carousels (topic_id, headline, caption, status, created_at) VALUES (?,?,?,?,?)",
                  (topic_id, c["headline"], c["caption"], "DRAFT", ts()))
    c["id"] = cid
    _persist(cid, c)
    execute("UPDATE topics SET status='CONVERTED' WHERE id=?", (topic_id,))
    log_event("creative", f"Draft #{cid} created from “{t['title'][:60]}” ({len(built)} slides)", cid)
    out = load_carousel(cid)
    out["note"] = None if len(built) == n else f"Only {len(built)} slides of verified material available (requested {n}); not padded."
    return out


def create_pack(topic_ids: List[int]) -> Dict[str, Any]:
    """One carousel showcasing several verified tools (like 'Comment PACK' posts)."""
    ids = list(dict.fromkeys(int(i) for i in topic_ids))[:8]
    if len(ids) < 2:
        raise ValueError("Pick at least 2 tools for a pack")
    topics = [topic_dict(i) for i in ids]
    if not all(topics) or any(t.get("verification_status") != "VERIFIED" for t in topics):
        raise ValueError("Every tool in a pack must be a verified topic")
    s = get_settings()
    kw = s.get("default_cta_keyword", "AGENT")
    readmes = {str(t["id"]): creative.fetch_readme(t.get("url", "")) for t in topics}
    items = [{"topic": t, "readme": readmes[str(t["id"])]} for t in topics]
    built = creative.build_pack(items, kw)
    title = creative.pack_title(topics)
    c = {
        "headline": title, "caption": creative.pack_caption(items, kw),
        "hashtags": creative.build_hashtags(topics[0], s.get("default_hashtags", "")), "cta_keyword": kw,
        "resource_pack": creative.dm_message(items),
        "slide_data": {"slides": built, "pack": ids, "readmes": readmes, "install": [],
                       "recommendation": {"format": "CAROUSEL", "slides": len(built), "reason": f"Pack of {len(ids)} tools: cover + one slide per tool + CTA."}},
        "design": {**creative.DEFAULT_DESIGN, "theme": s.get("default_theme", "studio"), "accent": s.get("default_accent", "#4C7DFF")},
        "post_format": "CAROUSEL", "topic": topics[0], "pack_topics": topics,
    }
    cid = execute("INSERT INTO carousels (topic_id, headline, caption, status, created_at) VALUES (?,?,?,?,?)",
                  (ids[0], title, c["caption"], "DRAFT", ts()))
    c["id"] = cid
    _persist(cid, c)
    execute(f"UPDATE topics SET status='CONVERTED' WHERE id IN ({','.join('?' * len(ids))})", ids)
    log_event("creative", f"Pack #{cid} created: {title}", cid)
    return load_carousel(cid)


def guide_items(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    sd = c["slide_data"]
    if sd.get("pack"):
        return [{"topic": t, "readme": sd.get("readmes", {}).get(str(t["id"]), {})} for t in c["pack_topics"]]
    return [{"topic": c["topic"], "readme": sd.get("readme") or {"install": sd.get("install", [])}}]


def guide_html(c: Dict[str, Any]) -> (str, int):
    s = get_settings()
    return creative.guide_document(guide_items(c), s.get("brand_name", "SONU AI LAB"), handle())


def update_carousel(cid: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    c = load_carousel(cid)
    if not c:
        raise ValueError("Carousel not found")
    if c["status"] in ("PUBLISHED", "PUBLISHING"):
        raise ValueError(f"Cannot edit a {c['status'].lower()} post")
    for k in EDITABLE & patch.keys():
        c[k] = str(patch[k])[:2200]
    if "cta_keyword" in patch:
        c["cta_keyword"] = re.sub(r"[^A-Za-z0-9_]", "", c["cta_keyword"]).upper()[:20]
        for sl in c["slide_data"].get("slides", []):
            if sl.get("layout", "").startswith("cta"):
                sl["keyword"] = c["cta_keyword"]
    if "slides" in patch:
        slides = patch["slides"]
        if not isinstance(slides, list) or not 1 <= len(slides) <= 10:
            raise ValueError("A post needs 1–10 slides")
        c["slide_data"]["slides"] = slides
        c["post_format"] = "SINGLE" if len(slides) == 1 else ("REEL" if c.get("post_format") == "REEL" else "CAROUSEL")
    if "design" in patch:
        d = patch["design"]
        c["design"] = {**c["design"], **{k: d[k] for k in ("theme", "accent", "font", "title_scale", "show_handle") if k in d}}
        if c["design"]["theme"] not in creative.THEMES or c["design"]["font"] not in creative.FONTS:
            raise ValueError("Unknown theme or font")
        c["design"]["title_scale"] = max(0.7, min(1.3, float(c["design"]["title_scale"])))
    if c["status"] in ("REJECTED", "PUBLISH_FAILED"):
        execute("UPDATE carousels SET status='DRAFT' WHERE id=?", (cid,))
    _persist(cid, c)
    return load_carousel(cid)


def handle() -> str:
    """The handle printed on slides/guides. Follows the connected Instagram account once it is known."""
    return get_setting("connected_handle", "") or get_setting("creator_handle", "")


def slide_html(c: Dict[str, Any], only: Optional[int] = None, for_render: bool = False) -> str:
    s = get_settings()
    doc = creative.slide_document(c["slide_data"].get("slides", []), c["design"], handle(),
                                  s.get("brand_name", "SONU AI LAB"), only)
    if for_render:  # uploaded assets: server URL → file URI so rendering works without the server
        doc = doc.replace('src="/api/media/', f'src="{OUTPUT_DIR.as_uri()}/')
        doc = doc.replace('referrerpolicy="no-referrer">', 'referrerpolicy="no-referrer" onerror="this.parentNode.remove()">')
    return doc


def render(cid: int, only: Optional[int] = None, ctx=None) -> Dict[str, Any]:
    c = load_carousel(cid)
    if not c or c["legacy"]:
        return {"success": False, "error": "Nothing to render (legacy post without slide data)"}
    slides = c["slide_data"]["slides"]
    if ctx:
        ctx.stage("Visual Creation", 30)
    prefix = f"carousels/{cid}"
    urls = media.render(slide_html(c, for_render=True), [f"slide_{i:02d}.jpg" for i in range(1, len(slides) + 1)], prefix)
    if ctx:
        ctx.stage("Visual Creation: DM guide", 70)
    doc, pages = guide_html(c)
    doc = doc.replace('referrerpolicy="no-referrer">', 'referrerpolicy="no-referrer" onerror="this.parentNode.remove()">')
    guide = media.render(doc, [f"guide_{i:02d}.jpg" for i in range(1, pages + 1)], prefix)
    execute("UPDATE carousels SET rendered_json=?, guide_json=?, rendered_at=? WHERE id=?", (json.dumps(urls), json.dumps(guide), ts(), cid))
    if ctx:
        ctx.log(f"Rendered {len(urls)} slide(s) + {len(guide)} guide page(s) for #{cid}")
    log_event("creative", f"Rendered {len(urls)} slide(s) for draft #{cid}", cid)
    return {"success": True, "rendered": urls, "guide": guide}


def regenerate(cid: int, slide_index: Optional[int] = None, count: Optional[int] = None) -> Dict[str, Any]:
    c = load_carousel(cid)
    if not c or not c["topic"]:
        raise ValueError("Carousel or source topic not found")
    slides = c["slide_data"]["slides"]
    if slide_index:
        if not 1 <= slide_index <= len(slides):
            raise ValueError("Slide index out of range")
        slides[slide_index - 1] = creative.regenerate_slide(slides[slide_index - 1], c["topic"])
        return update_carousel(cid, {"slides": slides})
    n = max(1, min(10, int(count or len(slides))))
    if c["slide_data"].get("pack"):
        c["slide_data"]["readmes"] = {str(t["id"]): creative.fetch_readme(t.get("url", "")) for t in c["pack_topics"]}
        execute("UPDATE carousels SET slide_data_json=? WHERE id=?", (json.dumps(c["slide_data"]), cid))
        built = creative.build_pack(guide_items(c), c["cta_keyword"])
        return update_carousel(cid, {"slides": built, "caption": creative.pack_caption(guide_items(c), c["cta_keyword"]),
                                     "resource_pack": creative.dm_message(guide_items(c))})
    readme = creative.fetch_readme(c["topic"].get("url", ""))
    c["slide_data"]["readme"], c["slide_data"]["install"] = readme, readme["install"] or c["slide_data"].get("install", [])
    built = creative.build_slides_v2(c["topic"], n, readme, c["cta_keyword"])
    c["slide_data"]["requested"] = n
    execute("UPDATE carousels SET slide_data_json=? WHERE id=?", (json.dumps(c["slide_data"]), cid))
    out = update_carousel(cid, {"slides": built, "caption": creative.build_caption(c["topic"], c["cta_keyword"]),
                                "resource_pack": creative.dm_message(guide_items({**c, "slide_data": c["slide_data"]}))})
    out["note"] = None if len(built) == n else f"Only {len(built)} slides of verified material available (requested {n}); not padded."
    return out


def submit(cid: int) -> Dict[str, Any]:
    c = load_carousel(cid)
    if c["status"] not in ("DRAFT", "REJECTED", "PUBLISH_FAILED"):
        raise ValueError(f"Cannot submit from {c['status']}")
    if c["render_stale"]:
        raise ValueError("Render the slides first — the preview has changed since the last render")
    execute("UPDATE carousels SET status='PENDING_APPROVAL', reject_reason='' WHERE id=?", (cid,))
    log_event("approval", f"#{cid} submitted for approval", cid)
    return load_carousel(cid)


def reject(cid: int, reason: str) -> Dict[str, Any]:
    c = load_carousel(cid)
    if c["status"] in ("PUBLISHED", "PUBLISHING"):
        raise ValueError("Cannot reject a published post")
    execute("UPDATE carousels SET status='REJECTED', reject_reason=? WHERE id=?", (reason[:300], cid))
    log_event("approval", f"#{cid} rejected: {reason[:80]}", cid)
    return load_carousel(cid)


QUEUE = ("PENDING_APPROVAL", "PUBLISH_FAILED")
STUCK_AFTER_MIN = 10  # a publish request can't outlive Vercel's 300 s limit; older PUBLISHING rows are orphans


def _caption(c: Dict[str, Any]) -> str:
    return f"{c['caption']}\n\n{c.get('hashtags', '')}".strip()


def _mark_published(cid: int, media_id: str, log=lambda *a: None) -> Dict[str, Any]:
    """The only place a post becomes PUBLISHED: Meta returned (or confirmed) a media id."""
    c = load_carousel(cid)
    permalink = meta.get_permalink(media_id) if media_id else ""
    update("UPDATE carousels SET status='PUBLISHED', publish_stage='PUBLISHED', ig_media_id=?, metricool_post_id=?, permalink=?, "
           "published_at=?, error_message='', publish_error_json='' WHERE id=?", (media_id, media_id, permalink, ts(), cid))
    if c.get("topic_id"):
        execute("UPDATE topics SET status='PUBLISHED' WHERE id=?", (c["topic_id"],))
    log_event("publish", f"#{cid} published to Instagram (media {media_id or 'id pending'})", cid)
    camp = auto_campaign(cid, media_id, log) if media_id else None
    return {"success": True, "media_id": media_id, "permalink": permalink, "campaign_id": camp}


def _already_published(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Before any new attempt: did an earlier, interrupted attempt actually go live?
    → {"published": media_id} | {"published": None} (Meta confirms it didn't) | {"error": msg} (can't tell)."""
    if c.get("ig_media_id"):
        return {"published": c["ig_media_id"]}  # Meta already gave us a media id for this post
    container = c.get("ig_container_id") or ""
    if not container:
        if c.get("publish_attempt_at") or c["status"] != "PUBLISHING":
            return {"published": None, "why": "never_sent"}  # media_publish is only ever sent after the container id is saved
        mid = meta.find_published_media(_caption(c), "")  # legacy row from before container tracking
        return {"published": mid, "why": "meta_confirmed"}
    st = meta.container_status(container)
    if not st["ok"]:
        if st["error"].get("code") == 100 or st["error"].get("http_status") == 400:  # container gone (expired) → never published
            return {"published": None, "why": "meta_confirmed"}
        return {"error": f"Couldn't confirm whether the earlier attempt was published: {format_error(st['error'])}"}
    if st["status_code"] == "PUBLISHED":
        return {"published": meta.find_published_media(_caption(c), c.get("publish_attempt_at", "")) or ""}
    return {"published": None, "why": "meta_confirmed"}


def publish(cid: int, ctx=None) -> Dict[str, Any]:
    """Publish to the configured Instagram account.
    Stages (carousels.publish_stage): VALIDATING → UPLOADING → PROCESSING → PUBLISHING → PUBLISHED; failures → status PUBLISH_FAILED.
    PUBLISHED is written only after Meta returns a media id. An atomic claim stops double publishing across instances."""
    log = ctx.log if ctx else (lambda *a: None)

    def stage(name: str, progress: int, detail: str = ""):
        update("UPDATE carousels SET publish_stage=? WHERE id=?", (name, cid))
        if ctx:
            ctx.stage(f"{name.title()}{': ' + detail if detail else ''}", progress)

    c = load_carousel(cid)
    if not c:
        return {"success": False, "error": "Carousel not found"}
    if c["status"] == "PUBLISHING":
        rec = recover_stuck_publishing(cid)
        if not rec or rec[0]["result"] == "still_publishing":
            return {"success": False, "error": "This post is already being published. Wait for it to finish, or use Check status.", "duplicate": True}
        c = load_carousel(cid)
        if c["status"] == "PUBLISHED":
            return {"success": True, "media_id": c["ig_media_id"], "permalink": c["permalink"], "reconciled": True}
    if c["status"] not in QUEUE:
        return {"success": False, "error": f"Only approved-queue posts can be published (status {c['status']})"}
    if c["render_stale"]:
        return {"success": False, "error": "Slides changed since last render — render before publishing"}
    files = c["rendered"]
    if not 1 <= len(files) <= 10:
        return {"success": False, "error": f"{len(files)} rendered slides; Instagram needs 1–10"}

    prev = dict(c)  # the earlier attempt's container info, needed for reconciliation after the claim resets it
    claimed = update("UPDATE carousels SET status='PUBLISHING', publish_stage='VALIDATING', publish_attempt_at=?, error_message='', "
                     "publish_error_json='' WHERE id=? AND status IN ('PENDING_APPROVAL','PUBLISH_FAILED')", (utc_now(), cid))
    if claimed != 1:
        return {"success": False, "error": "This post is already being published (another click or tab got there first).", "duplicate": True}
    attempt_at = one("SELECT publish_attempt_at FROM carousels WHERE id=?", (cid,))["publish_attempt_at"]

    def fail(msg: str, err: Optional[Dict[str, Any]] = None):
        update("UPDATE carousels SET status='PUBLISH_FAILED', error_message=?, publish_error_json=? WHERE id=?",
               (msg[:1000], json.dumps(err or {"message": msg}), cid))
        log_event("publish", f"#{cid} publish failed: {msg[:160]}", cid)
        log(f"FAILED: {msg}")
        return {"success": False, "error": msg, "meta_error": err}

    # ---- VALIDATING: account, token, permission, earlier attempt, images
    stage("VALIDATING", 5, "checking the Instagram account")
    meta.reload()
    diag = meta._get(meta.ig_user_id, fields="username")
    if not diag["ok"]:
        e = {"code": diag.get("code"), "subcode": diag.get("subcode"), "message": diag.get("error", ""), "kind": "meta"}
        e["hint"] = "The Instagram access token is expired or invalid. Renew it in Settings." if e["code"] == 190 else ""
        return fail(f"Meta account check failed: {format_error(e)}", e)
    log(f"Publishing to @{diag['data'].get('username')} ({meta.ig_user_id})")
    scopes = meta.token_scopes()
    if scopes is not None and "instagram_content_publish" not in scopes:
        return fail("The access token is missing the instagram_content_publish permission → Reconnect Instagram in Settings with that permission.",
                    {"kind": "permission", "message": "missing instagram_content_publish", "scopes": scopes})
    if prev.get("ig_container_id") or prev["status"] == "PUBLISHING":
        earlier = _already_published(prev)
        if "error" in earlier:
            return fail(earlier["error"] + " Not retrying, to avoid a duplicate post. Use Check status in a few minutes.")
        if earlier["published"] is not None:
            log("An earlier attempt is already live on Instagram — not publishing again")
            return _mark_published(cid, earlier["published"], log)

    stage("VALIDATING", 12, "checking slide images")
    urls = []
    for i, f in enumerate(files, 1):
        u = media.public_url(f)
        if not u:
            return fail(f"Could not stage slide {i} on a public HTTPS host")
        ok, why = check_image_url(u)
        if not ok:
            return fail(f"Slide {i} image {why} → Re-render the slides, then retry.", {"kind": "image", "slide": i, "message": why, "url": u})
        urls.append(u)
        log(f"Slide {i}: {u[:80]}")
    caption = _caption(c)

    # ---- UPLOADING: one container per image
    single = len(urls) == 1
    stage("UPLOADING", 25, "sending images to Instagram")
    if single:
        r = meta.create_container(urls[0], caption)
        if not r["ok"]:
            return fail(format_error(r["error"]), r["error"])
        parent, children = r["data"]["id"], []
        update("UPDATE carousels SET ig_container_id=?, ig_children_json='[]' WHERE id=?", (parent, cid))
    else:
        children = []
        for i, u in enumerate(urls, 1):
            r = meta.create_container(u, carousel_item=True)
            if not r["ok"]:
                return fail(f"Slide {i}: {format_error(r['error'])}", {**r["error"], "slide": i})
            children.append(r["data"]["id"])
            update("UPDATE carousels SET ig_children_json=? WHERE id=?", (json.dumps(children), cid))
            stage("UPLOADING", 25 + int(25 * i / len(urls)), f"slide {i}/{len(urls)}")

    # ---- PROCESSING: every child, then the parent, must be FINISHED before publishing
    stage("PROCESSING", 55, "waiting for Meta to process the images")
    for i, ch in enumerate(children, 1):
        w = meta.wait_container(ch)
        if not w["ok"]:
            return fail(f"Slide {i}: {format_error(w['error'])}", {**w["error"], "slide": i})
    if not single:
        r = meta.create_carousel_container(children, caption)
        if not r["ok"]:
            return fail(format_error(r["error"]), r["error"])
        parent = r["data"]["id"]
        update("UPDATE carousels SET ig_container_id=? WHERE id=?", (parent, cid))
    w = meta.wait_container(parent)
    if not w["ok"]:
        return fail(format_error(w["error"]), w["error"])

    # ---- PUBLISHING: from here an interrupted request may or may not have gone live → always reconcile, never blind-retry
    stage("PUBLISHING", 85, "publishing")
    r = meta.publish_creation(parent)
    if r["ok"]:
        stage("PUBLISHING", 95, "confirmed by Meta")
        return _mark_published(cid, r["data"].get("id", ""), log)
    if r["error"].get("uncertain"):
        log(f"media_publish outcome unknown ({r['error']['message']}); checking with Meta")
        for _ in range(3):
            st = meta.container_status(parent)
            if st["ok"] and st["status_code"] == "PUBLISHED":
                return _mark_published(cid, meta.find_published_media(caption, attempt_at) or "", log)
            if st["ok"] and st["status_code"] in ("FINISHED", "ERROR", "EXPIRED"):
                return fail(f"Meta confirms the post was NOT published ({format_error(r['error'])}). Safe to retry.", r["error"])
            time.sleep(POLL_INTERVAL_S)
        update("UPDATE carousels SET error_message=? WHERE id=?",
               ("Publish result unknown: Meta didn't answer. Left in Publishing; Check status confirms it before any retry.", cid))
        return {"success": False, "error": "Publish result unknown. Use Check status in a few minutes — it won't publish twice.", "uncertain": True}
    return fail(format_error(r["error"]), r["error"])


def recover_stuck_publishing(cid: Optional[int] = None, older_than_min: int = STUCK_AFTER_MIN) -> List[Dict[str, Any]]:
    """Posts left in PUBLISHING (function killed, timeout, unknown media_publish result) are reconciled against Meta:
    live → PUBLISHED; confirmed not live → PUBLISH_FAILED (retry allowed); can't tell → left alone."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sql, args = "SELECT id FROM carousels WHERE status='PUBLISHING' AND (publish_attempt_at='' OR publish_attempt_at IS NULL OR publish_attempt_at < ?)", [cutoff]
    if cid is not None:
        sql, args = sql + " AND id=?", args + [cid]
    out = []
    rows = query(sql, tuple(args))
    if rows:
        meta.reload()
    for row in rows:
        c = load_carousel(row["id"])
        res = _already_published(c)
        if "error" in res:
            out.append({"id": c["id"], "result": "still_publishing", "error": res["error"]})
            continue
        if res["published"] is not None:
            _mark_published(c["id"], res["published"])
            out.append({"id": c["id"], "result": "published", "media_id": res["published"]})
            continue
        msg = ("The publish was interrupted before anything was sent to Instagram for publishing. Safe to retry."
               if res.get("why") == "never_sent" else
               "The publish was interrupted and Meta confirms the post did not go live. Safe to retry.")
        if update("UPDATE carousels SET status='PUBLISH_FAILED', error_message=?, publish_error_json=? WHERE id=? AND status='PUBLISHING'",
                  (msg, json.dumps({"kind": "interrupted", "message": msg}), c["id"])):
            log_event("publish", f"#{c['id']} recovered from a stuck publish: not live, retry allowed", c["id"])
        out.append({"id": c["id"], "result": "failed_safe_to_retry"})
    return out


def auto_campaign(cid: int, media_id: str, log=lambda *a: None) -> Optional[int]:
    """Every published post gets its Comment-to-DM campaign automatically: keyword → button flow → guide pages + text."""
    c = load_carousel(cid)
    s = get_settings()
    urls = []
    for f in c["guide"][:6]:
        u = media.public_url(f)
        if u:
            urls.append(u)
    log(f"Guide pages staged for DM: {len(urls)}")
    active = 1 if s.get("auto_dm", "1") == "1" else 0
    camp = execute("""INSERT INTO campaigns (name, keyword, media_id, carousel_id, active, private_reply, follow_gate, follow_gate_message,
                      resource_pack, guide_images, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (c["headline"][:80], c["cta_keyword"], media_id, cid, active, s.get("dm_opener", ""),
                    1 if s.get("dm_follow_gate", "1") == "1" else 0, s.get("dm_not_following", ""),
                    c["resource_pack"], json.dumps(urls), ts(), ts()))
    log_event("dm", f"Auto-reply {'ON' if active else 'created (paused)'} for “{c['cta_keyword']}” on post #{cid}", camp)
    return camp


def run_research(ctx) -> Dict[str, Any]:
    s = get_settings()
    cats = [x for x in s.get("auto_categories", "").split(",") if x in CATEGORIES]
    items = harvester.run_daily_harvest(ctx, int(s.get("max_research_items", "40")), cats or None)
    execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_research_at', ?)", (ts(),))
    return {"success": True, "found": len(items), "verified": sum(i.get("verification_status") == "VERIFIED" for i in items)}


def published_today() -> int:
    return one("SELECT COUNT(*) n FROM carousels WHERE status='PUBLISHED' AND published_at LIKE ?", (now_ist().strftime("%Y-%m-%d") + "%",))["n"]


def run_pipeline(ctx) -> Dict[str, Any]:
    s = get_settings()
    mode, min_score = s.get("publishing_mode", "REVIEW"), int(s.get("min_qc_score", "85"))
    if not (s.get("last_research_at") or "").startswith(now_ist().strftime("%Y-%m-%d")):
        ctx.log("No research yet today — running research first")
        run_research(ctx)
    ctx.stage("Content Selection", 55)
    cats = [x for x in s.get("auto_categories", "").split(",") if x]
    marks = ",".join("?" * len(cats)) or "''"
    t = one(f"""SELECT * FROM topics WHERE status='NEW' AND verification_status='VERIFIED' AND category IN ({marks})
               ORDER BY opportunity_score DESC, id DESC LIMIT 1""", cats)
    if not t:
        return {"success": False, "error": "No verified, unused topic in the selected categories"}
    ctx.log(f"Selected [{t['opportunity_score']}] {t['title']}")
    ctx.stage("Content Generation", 65)
    c = create_from_topic(t["id"])
    cid = c["id"]
    render(cid, ctx=ctx)
    ctx.stage("Quality Assurance", 85)
    c = load_carousel(cid)
    ctx.log(f"QC {c['quality_score']}/100 (threshold {min_score})")
    if c["quality_score"] < min_score:
        return {"success": True, "carousel_id": cid, "status": "DRAFT", "note": "Below QC threshold — left as draft for editing"}
    submit(cid)
    if mode == "AUTO":
        if published_today() >= int(s.get("max_posts_per_day", "1")):
            return {"success": True, "carousel_id": cid, "status": "PENDING_APPROVAL", "note": "Daily post limit reached"}
        return {**publish(cid, ctx), "carousel_id": cid}
    return {"success": True, "carousel_id": cid, "status": "PENDING_APPROVAL"}


# ====================================================================== Phase 5: independent scheduled jobs
# research (run_research above) · generate · publish_due · analytics. Each is short enough for one serverless call,
# none calls another; the scheduler (scheduler/jobs.py) runs them at their own times.
from config import IST  # noqa: E402

GENERATE_LEAD_MIN = 45     # "" generate_time = this many minutes before the publishing time
MISSED_AFTER_H = 12        # an approved post more than this late is not published automatically


def _hhmm_shift(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":")[:2])
    t = (h * 60 + m + minutes) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


def schedule_times(s: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Wall-clock HH:MM in the dashboard timezone (Asia/Kolkata) for each daily job."""
    s = s or get_settings()
    publish_t = s.get("target_publish_time") or "19:00"
    return {"research": s.get("research_time") or "17:30",
            "generate": s.get("generate_time") or _hhmm_shift(publish_t, -GENERATE_LEAD_MIN),
            "publish": publish_t,
            "analytics": s.get("analytics_time") or "23:30"}


def ist_to_utc(local: str) -> str:
    """'2026-11-21T19:00' (dashboard, Asia/Kolkata) → '2026-11-21T13:30:00Z'."""
    dt = datetime.strptime(local.strip()[:16].replace(" ", "T"), "%Y-%m-%dT%H:%M").replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_to_ist(utc_iso: str) -> str:
    dt = datetime.strptime(utc_iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M")


def next_publish_utc(s: Optional[Dict[str, str]] = None, now: Optional[datetime] = None) -> str:
    """Next occurrence of the publishing time (today if still ahead, else tomorrow), as UTC."""
    now = (now or now_ist()).astimezone(IST)
    h, m = map(int, schedule_times(s)["publish"].split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now:
        t += timedelta(days=1)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule_post(cid: int, when_utc: str) -> Dict[str, Any]:
    """Approve a queued post for publishing at when_utc (UTC ISO). publish_due picks it up."""
    c = load_carousel(cid)
    if not c:
        raise ValueError("Carousel not found")
    if c["status"] not in QUEUE:
        raise ValueError(f"Only posts in the approval queue can be scheduled (status {c['status']})")
    if c["render_stale"]:
        raise ValueError("Render the slides first — the preview has changed since the last render")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", when_utc or ""):
        raise ValueError("Scheduled time must be a UTC ISO timestamp")
    update("UPDATE carousels SET status='PENDING_APPROVAL', scheduled_for=?, approved_at=?, error_message='' WHERE id=? AND status IN ('PENDING_APPROVAL','PUBLISH_FAILED')",
           (when_utc, utc_now(), cid))
    log_event("approval", f"#{cid} approved and scheduled for {utc_to_ist(when_utc)} IST", cid)
    return load_carousel(cid)


def unschedule_post(cid: int) -> Dict[str, Any]:
    update("UPDATE carousels SET scheduled_for='', approved_at='' WHERE id=? AND status IN ('PENDING_APPROVAL','PUBLISH_FAILED')", (cid,))
    log_event("approval", f"#{cid} schedule cleared", cid)
    return load_carousel(cid)


def run_generate(ctx) -> Dict[str, Any]:
    """Create one post from the best verified unused topic, render, QC. Review Mode → waits for approval;
    Auto Mode → approved and scheduled for the next publishing time (publish_due publishes it). Never publishes itself."""
    s = get_settings()
    mode, min_score = s.get("publishing_mode", "REVIEW"), int(s.get("min_qc_score", "85"))
    ctx.stage("Content Selection", 10)
    cats = [x for x in s.get("auto_categories", "").split(",") if x]
    marks = ",".join("?" * len(cats)) or "''"
    t = one(f"""SELECT * FROM topics WHERE status='NEW' AND verification_status='VERIFIED' AND category IN ({marks})
               ORDER BY opportunity_score DESC, id DESC LIMIT 1""", cats)
    if not t:  # nothing to do is not a failure (no point retrying)
        return {"success": True, "status": "NOTHING_TO_DO", "note": "No verified, unused topic in the selected categories. Run research first."}
    ctx.log(f"Selected [{t['opportunity_score']}] {t['title']}")
    ctx.stage("Content Generation", 30)
    cid = create_from_topic(t["id"])["id"]
    render(cid, ctx=ctx)
    ctx.stage("Quality Assurance", 85)
    c = load_carousel(cid)
    ctx.log(f"QC {c['quality_score']}/100 (threshold {min_score})")
    if c["quality_score"] < min_score:
        return {"success": True, "carousel_id": cid, "status": "DRAFT", "note": "Below QC threshold, left as a draft for editing"}
    submit(cid)
    if mode == "AUTO":
        when = next_publish_utc(s)
        schedule_post(cid, when)
        return {"success": True, "carousel_id": cid, "status": "SCHEDULED", "scheduled_for": when,
                "note": f"Auto Mode: approved for {utc_to_ist(when)} IST"}
    return {"success": True, "carousel_id": cid, "status": "PENDING_APPROVAL", "note": "Review Mode: waiting for your approval"}


def due_post(now_utc: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Oldest approved post whose scheduled time has come. Legacy rows (no approved_at) are never picked."""
    return one("""SELECT id, scheduled_for FROM carousels WHERE status='PENDING_APPROVAL' AND approved_at!='' AND approved_at IS NOT NULL
                  AND scheduled_for!='' AND scheduled_for IS NOT NULL AND scheduled_for <= ? ORDER BY scheduled_for, id LIMIT 1""",
               (now_utc or utc_now(),))


def run_publish_due(ctx) -> Dict[str, Any]:
    """Publish at most one due, approved post per run (stays inside the function time limit). Failed publishes are not
    retried automatically: publish() records the Meta error and the dashboard offers a safe retry."""
    s = get_settings()
    row = due_post()
    if not row:
        return {"success": True, "status": "NOTHING_DUE"}
    cid = row["id"]
    late = datetime.now(timezone.utc) - datetime.strptime(row["scheduled_for"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if late > timedelta(hours=MISSED_AFTER_H):
        update("UPDATE carousels SET approved_at='', error_message=? WHERE id=?",
               (f"Missed its scheduled time ({utc_to_ist(row['scheduled_for'])} IST) by over {MISSED_AFTER_H} h; not published automatically. Reschedule or publish now.", cid))
        log_event("publish", f"#{cid} missed its schedule; left for you to reschedule", cid)
        return {"success": True, "status": "MISSED", "carousel_id": cid}
    if published_today() >= int(s.get("max_posts_per_day", "1")):
        return {"success": True, "status": "LIMIT", "carousel_id": cid, "note": "Daily post limit reached; it will go out tomorrow"}
    ctx.log(f"Publishing #{cid} scheduled for {utc_to_ist(row['scheduled_for'])} IST")
    return {**publish(cid, ctx), "carousel_id": cid}


def run_analytics(ctx) -> Dict[str, Any]:
    """Refresh stored metrics for recent posts (read-only Graph calls)."""
    meta.reload()
    ctx.stage("Analytics: reading recent posts", 20)
    r = meta.get_recent_media(25)
    if not r.get("success"):
        return {"success": False, "error": f"Couldn't read recent media: {r.get('error')}"}
    n = 0
    for m in r.get("media", []):
        ins = m.get("insights") or {}
        likes, comments = int(m.get("like_count") or 0), int(m.get("comments_count") or 0)
        reach, saved, shares = int(ins.get("reach") or 0), int(ins.get("saved") or 0), int(ins.get("shares") or 0)
        rate = round((likes + comments + saved + shares) / reach * 100, 2) if reach else 0.0
        vals = (reach, likes, comments, saved, shares, rate, m.get("media_product_type") or m.get("media_type") or "", ts())
        if not update("UPDATE post_insights SET reach=?, likes=?, comments=?, saved=?, shares=?, engagement_rate=?, post_format=?, updated_at=? WHERE post_id=?",
                      (*vals, m["id"])):
            update("INSERT OR IGNORE INTO post_insights (reach, likes, comments, saved, shares, engagement_rate, post_format, updated_at, post_id) VALUES (?,?,?,?,?,?,?,?,?)",
                   (*vals, m["id"]))
        n += 1
    return {"success": True, "posts_updated": n}

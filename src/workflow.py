"""Content workflow: topic → carousel draft → render → QC → approval → publish. Used by API + scheduler."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CATEGORIES, OUTPUT_DIR
from generator import creative
from meta_graph_client import MetaGraphClient
from qc.evaluator import QualityControlEvaluator
from research.harvester import ResearchHarvester, recommend_format
from store import execute, get_setting, get_settings, log_event, now_ist, one, query, ts
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


def publish(cid: int, ctx=None) -> Dict[str, Any]:
    """Publish to the configured Instagram account. PUBLISHED is written only after Meta returns a media id."""
    step = ctx.stage if ctx else (lambda *a: None)
    log = ctx.log if ctx else (lambda *a: None)
    c = load_carousel(cid)
    if not c:
        return {"success": False, "error": "Carousel not found"}
    if c["status"] not in ("PENDING_APPROVAL", "PUBLISH_FAILED"):
        return {"success": False, "error": f"Only approved-queue posts can be published (status {c['status']})"}
    if c["render_stale"]:
        return {"success": False, "error": "Slides changed since last render — render before publishing"}
    files = c["rendered"]
    if not 1 <= len(files) <= 10:
        return {"success": False, "error": f"{len(files)} rendered slides; Instagram needs 1–10"}

    def fail(msg):
        execute("UPDATE carousels SET status='PUBLISH_FAILED', error_message=? WHERE id=?", (msg[:500], cid))
        log_event("publish", f"#{cid} publish failed: {msg[:120]}", cid)
        return {"success": False, "error": msg}

    meta.reload()
    step("Instagram Publishing: checking account", 10)
    diag = meta._get(meta.ig_user_id, fields="username")
    if not diag["ok"]:
        return fail(f"Meta account check failed: {diag['error']}")
    log(f"Publishing to @{diag['data'].get('username')} ({meta.ig_user_id})")
    execute("UPDATE carousels SET status='PUBLISHING', error_message='' WHERE id=?", (cid,))
    step("Instagram Publishing: staging images", 30)
    urls = []
    for i, f in enumerate(files, 1):
        u = media.public_url(f)
        if not u:
            return fail(f"Could not stage slide {i} on a public HTTPS host")
        urls.append(u)
        log(f"Slide {i}: {u[:80]}")
    caption = f"{c['caption']}\n\n{c.get('hashtags', '')}".strip()
    step("Instagram Publishing: creating containers", 60)
    res = meta.publish_single_image(urls[0], caption) if len(urls) == 1 else meta.publish_carousel(urls, caption)
    if not res.get("success"):
        return fail(str(res.get("error"))[:500])
    media_id = res["post_id"]
    permalink = meta.get_permalink(media_id)
    step("Instagram Publishing: confirmed", 95)
    execute("UPDATE carousels SET status='PUBLISHED', ig_media_id=?, metricool_post_id=?, permalink=?, published_at=? WHERE id=?",
            (media_id, media_id, permalink, ts(), cid))
    if c.get("topic_id"):
        execute("UPDATE topics SET status='PUBLISHED' WHERE id=?", (c["topic_id"],))
    log_event("publish", f"#{cid} published to Instagram (media {media_id})", cid)
    camp = auto_campaign(cid, media_id, log)
    return {"success": True, "media_id": media_id, "permalink": permalink, "campaign_id": camp}


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

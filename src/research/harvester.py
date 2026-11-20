"""Daily research engine (v3) — real sources only.

Sources:
  * GitHub Search API  — new repos gaining stars (trending, MCP/dev tools, creator, video, tutorials)
  * Hacker News Algolia — AI industry stories with real points/comments/timestamps
  * Hugging Face Hub    — trending open models
Every candidate keeps its original URL and publication date. The top candidates are verified by
fetching the source (HTTP status, og:image, description). Nothing here is hand-written.
"""

import difflib
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import requests

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

sys.path.append(str(Path(__file__).resolve().parent.parent))
from store import get_db, ts  # noqa: E402

logger = logging.getLogger("ResearchHarvester")
UA = {"User-Agent": "SonuAILab-ResearchBot/3.0 (+local)"}

FOCUS = ["agent", "mcp", "model context protocol", "claude", "gpt", "openai", "anthropic", "gemini", "deepseek",
         "llm", "video", "voice", "speech", "image", "animation", "creator", "editing", "open-source", "open source",
         "github", "release", "launch", "coding", "automation", "workflow", "local"]
PRACTICAL = ["open-source", "open source", "free", "local", "cli", "api", "sdk", "tool", "build", "automate",
             "self-hosted", "plugin", "extension", "app", "framework", "template", "starter"]


def _iso_date(s: str) -> str:
    return (s or "")[:10]


def _age_days(date_str: str) -> float:
    try:
        d = datetime.fromisoformat(date_str[:10]).replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - d).total_seconds() / 86400, 0.5)
    except Exception:
        return 30.0


def normalize_url(url: str) -> str:
    p = urlparse((url or "").strip())
    q = "&".join(x for x in p.query.split("&") if x and not x.startswith("utm_"))
    return urlunparse(("https", p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", q, ""))


class ResearchHarvester:
    def __init__(self):
        self.gh_headers = {"Accept": "application/vnd.github+json", **UA}
        if os.getenv("GITHUB_TOKEN"):
            self.gh_headers["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"

    # ------------------------------------------------------------ sources
    def _github(self, q: str, category: str, per_page: int = 6) -> List[Dict[str, Any]]:
        r = requests.get("https://api.github.com/search/repositories",
                         params={"q": q, "sort": "stars", "order": "desc", "per_page": per_page},
                         headers=self.gh_headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"GitHub search {r.status_code}: {r.text[:120]}")
        return [self._repo_item(repo, category) for repo in r.json().get("items", [])]

    def _repo_item(self, repo: Dict[str, Any], category: str) -> Dict[str, Any]:
        stars = repo.get("stargazers_count", 0)
        created, pushed = _iso_date(repo.get("created_at")), _iso_date(repo.get("pushed_at"))
        lic = (repo.get("license") or {}).get("spdx_id") or ""
        facts = [f"{stars:,} GitHub stars", f"Created {created}", f"Last commit {pushed}"]
        if repo.get("language"):
            facts.append(f"Written in {repo['language']}")
        if lic and lic != "NOASSERTION":
            facts.append(f"License: {lic}")
        if repo.get("topics"):
            facts.append("Topics: " + ", ".join(repo["topics"][:5]))
        per_day = round(stars / _age_days(created))
        return {
            "title": repo["full_name"], "source": "GitHub", "source_kind": "github",
            "url": repo["html_url"], "description": repo.get("description") or "",
            "category": category, "published_date": created, "stars": stars,
            "language": repo.get("language") or "", "cost_type": "Open Source" if lic else "Source available",
            "why_it_matters": f"{stars:,} stars since {created} (~{per_day:,}/day); last commit {pushed}.",
            "preview_image_url": f"https://opengraph.githubassets.com/1/{repo['full_name']}",
            "facts": facts, "_velocity": per_day,
        }


    def harvest_github(self) -> List[Dict[str, Any]]:
        d = lambda n: (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731
        queries = [
            (f"agent OR llm OR ai created:>{d(30)} stars:>200", "Trending GitHub"),
            (f"mcp OR \"model context protocol\" OR \"coding agent\" created:>{d(90)} stars:>80", "AI Developer Tools"),
            (f"\"text-to-speech\" OR \"voice cloning\" OR \"image generation\" OR creator created:>{d(120)} stars:>80", "AI Creator Tools"),
            (f"\"video generation\" OR \"video editing\" OR \"text-to-video\" OR animation created:>{d(120)} stars:>60", "Video & Animation"),
            (f"tutorial OR cookbook OR workflow OR course llm created:>{d(90)} stars:>80", "Tutorials & Workflows"),
        ]
        out = []
        for q, cat in queries:
            try:
                out += self._github(q, cat)
            except Exception as e:
                logger.warning(f"GitHub query failed ({cat}): {e}")
        return out

    def harvest_hn(self) -> List[Dict[str, Any]]:
        since = int(time.time()) - 3 * 86400
        seen, out = set(), []
        for term in ["OpenAI", "Anthropic", "Claude", "Gemini", "LLM", "AI agent", "open model", "AI video"]:
            try:
                r = requests.get("https://hn.algolia.com/api/v1/search", timeout=12, headers=UA, params={
                    "query": term, "tags": "story", "hitsPerPage": 6,
                    "numericFilters": f"created_at_i>{since},points>40"})
                r.raise_for_status()
            except Exception as e:
                logger.warning(f"HN query '{term}' failed: {e}")
                continue
            for h in r.json().get("hits", []):
                if h["objectID"] in seen or not h.get("url"):
                    continue
                seen.add(h["objectID"])
                title, url = h.get("title", ""), h["url"]
                tl = title.lower()
                if "github.com" in url:
                    cat = "Open-Source Projects"
                elif re.search(r"\b(how to|tutorial|guide|walkthrough|building|i built)\b", tl):
                    cat = "Tutorials & Workflows"
                elif re.search(r"\b(video|animation|sora|veo)\b", tl):
                    cat = "Video & Animation"
                elif re.search(r"\b(cli|sdk|api|ide|tool|mcp|copilot|cursor|agent)\b", tl):
                    cat = "AI Developer Tools"
                else:
                    cat = "AI Industry News"
                out.append({
                    "title": title, "source": urlparse(url).netloc.removeprefix("www."), "source_kind": "hn",
                    "url": url, "description": "", "category": cat,
                    "published_date": _iso_date(h.get("created_at")), "stars": h.get("points", 0),
                    "why_it_matters": f"{h.get('points', 0)} points and {h.get('num_comments', 0)} comments on Hacker News.",
                    "facts": [f"{h.get('points', 0)} points on Hacker News", f"{h.get('num_comments', 0)} comments",
                              f"Published {_iso_date(h.get('created_at'))}",
                              f"Discussion: news.ycombinator.com/item?id={h['objectID']}"],
                    "cost_type": "", "_velocity": h.get("points", 0) / 3,
                })
        return out

    def harvest_huggingface(self) -> List[Dict[str, Any]]:
        try:
            r = requests.get("https://huggingface.co/api/models", headers=UA, timeout=12,
                             params={"sort": "trendingScore", "direction": -1, "limit": 12})
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"Hugging Face failed: {e}")
            return []
        out = []
        for m in r.json():
            tag = m.get("pipeline_tag") or ""
            if tag in ("text-to-video", "image-to-video"):
                cat = "Video & Animation"
            elif tag in ("text-to-speech", "text-to-image", "audio-to-audio", "image-to-image", "text-to-audio"):
                cat = "AI Creator Tools"
            else:
                cat = "Open-Source Projects"
            lic = next((t.split(":", 1)[1] for t in m.get("tags", []) if t.startswith("license:")), "")
            created = _iso_date(m.get("createdAt"))
            facts = [f"{m.get('likes', 0):,} likes on Hugging Face", f"{m.get('downloads', 0):,} downloads (30d)",
                     f"Released {created}"]
            if tag:
                facts.append(f"Task: {tag}")
            if lic:
                facts.append(f"License: {lic}")
            out.append({
                "title": m["id"], "source": "Hugging Face", "source_kind": "hf",
                "url": f"https://huggingface.co/{m['id']}", "description": "", "category": cat,
                "published_date": created, "stars": m.get("likes", 0), "cost_type": "Open weights" if lic else "",
                "why_it_matters": f"Trending on Hugging Face with {m.get('likes', 0):,} likes since {created}.",
                "facts": facts, "_velocity": m.get("likes", 0) / _age_days(created),
            })
        return out

    # ------------------------------------------------------------ verification
    def verify(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch the original source. VERIFIED only if it answers 2xx/3xx; pulls og:image + description."""
        try:
            r = requests.get(item["url"], headers={**UA, "Accept": "text/html,*/*"}, timeout=8, stream=True, allow_redirects=True)
            body = b""
            if "html" in r.headers.get("content-type", ""):
                for chunk in r.iter_content(16384):
                    body += chunk
                    if len(body) > 300_000 or b"</head>" in body:
                        break
            r.close()
            if r.status_code in (401, 403, 429, 451, 499):
                item["verification_status"] = "RESTRICTED"
                item["verification_note"] = f"Source exists but blocks automated checks (HTTP {r.status_code}) — open it to confirm"
                return item
            if r.status_code >= 400:
                item["verification_status"] = "UNREACHABLE"
                item["verification_note"] = f"Source returned HTTP {r.status_code} on {ts()}"
                return item
            html = body.decode("utf-8", "ignore")

            def meta(prop):
                m = re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]*content=["\']([^"\']+)', html, re.I) or \
                    re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{prop}["\']', html, re.I)
                return unescape(m.group(1)).strip() if m else ""

            if not item.get("preview_image_url"):
                img = meta("og:image") or meta("twitter:image")
                if img.startswith("//"):
                    img = "https:" + img
                item["preview_image_url"] = img if img.startswith("http") else ""
            if not item.get("description"):
                item["description"] = (meta("og:description") or meta("description"))[:400]
            item["verification_status"] = "VERIFIED"
            item["verification_note"] = f"Source reachable (HTTP {r.status_code}) on {ts()}"
        except Exception as e:
            item["verification_status"] = "UNREACHABLE"
            item["verification_note"] = f"Fetch failed: {type(e).__name__}"
        return item

    # ------------------------------------------------------------ scoring
    def score(self, item: Dict[str, Any]) -> Dict[str, Any]:
        text = f"{item.get('title', '')} {item.get('description', '')}".lower()
        useful = 40 + 8 * sum(k in text for k in PRACTICAL)
        age = _age_days(item.get("published_date", ""))
        velocity = item.get("_velocity") or (item.get("stars") or 0) / age  # stars, HN points or HF likes per day
        useful += 15 if item.get("source_kind") in ("github", "hf") else 0
        useful += min(20, int(velocity ** 0.5))
        relevant = 35 + 7 * sum(k in text for k in FOCUS)
        relevant += 10 if item.get("category") == "AI Industry News" else 0
        relevant += 20 if age <= 3 else 10 if age <= 14 else 0
        item["usefulness"], item["relevance"] = min(useful, 100), min(relevant, 100)
        item["opportunity_score"] = round(0.5 * item["usefulness"] + 0.5 * item["relevance"])
        fmt = recommend_format(item)
        item["suggested_format"], item["suggested_slides"] = fmt["format"], fmt["slides"]
        return item

    # ------------------------------------------------------------ pipeline
    def run_daily_harvest(self, ctx=None, max_items: int = 40, categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        step = (lambda n, p: ctx.stage(n, p)) if ctx else (lambda n, p: None)
        log = ctx.log if ctx else logger.info

        step("AI Intelligence: Hacker News", 10)
        items = self.harvest_hn()
        log(f"Hacker News: {len(items)} AI stories in last 72h")
        step("GitHub Discovery", 30)
        gh = self.harvest_github()
        log(f"GitHub: {len(gh)} repositories")
        step("Tools Discovery: Hugging Face", 45)
        hf = self.harvest_huggingface()
        log(f"Hugging Face: {len(hf)} trending models")
        items += gh + hf
        if categories:
            items = [i for i in items if i["category"] in categories]

        # dedupe against DB + within batch
        with get_db() as conn:
            existing = [(r["url"], r["title"]) for r in conn.execute("SELECT url, title FROM topics")]
        known_urls = {normalize_url(u or "") for u, _ in existing}
        known_titles = [t.lower() for _, t in existing]
        fresh, seen = [], set()
        for i in items:
            nu = normalize_url(i["url"])
            if nu in known_urls or nu in seen:
                continue
            if any(difflib.SequenceMatcher(None, i["title"].lower(), t).ratio() > 0.88 for t in known_titles):
                continue
            seen.add(nu)
            fresh.append(self.score(i))
        fresh.sort(key=lambda x: x["opportunity_score"], reverse=True)
        fresh = fresh[:max_items]
        log(f"{len(items)} candidates → {len(fresh)} new after de-duplication (cap {max_items})")

        step("Research Verification", 60)
        with ThreadPoolExecutor(8) as pool:
            fresh = list(pool.map(self.verify, fresh))
        ok = sum(i["verification_status"] == "VERIFIED" for i in fresh)
        log(f"Verified {ok}/{len(fresh)} sources")

        step("Scoring & storing", 85)
        saved = 0
        with get_db() as conn:
            for i in fresh:
                self.score(i)  # re-score: verify() may have filled in the description
                cur = conn.execute("""INSERT OR IGNORE INTO topics (title, source, url, description, pillar,
                    opportunity_score, category, published_date, verified_date, why_it_matters, target_audience,
                    practical_use_case, cost_type, stars, language, preview_image_url, verification_status,
                    verification_note, usefulness, relevance, suggested_format, suggested_slides, facts_json,
                    source_kind, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    i["title"], i["source"], i["url"], i.get("description", ""), i["category"],
                    i["opportunity_score"], i["category"], i.get("published_date", ""), ts()[:10],
                    i.get("why_it_matters", ""), audience_for(i["category"]), i.get("description", ""),
                    i.get("cost_type", ""), i.get("stars", 0), i.get("language", ""), i.get("preview_image_url", ""),
                    i["verification_status"], i.get("verification_note", ""), i["usefulness"], i["relevance"],
                    i["suggested_format"], i["suggested_slides"], json.dumps(i.get("facts", [])), i["source_kind"],
                    priority(i), ts()))
                saved += cur.rowcount
        log(f"Stored {saved} new topics")
        log(f"Re-scored {rescore_library()} existing topics")
        return fresh

    def verify_topic(self, topic: Dict[str, Any]) -> Dict[str, Any]:
        """Re-verify an existing topic; refreshes GitHub stats from the API when it is a repo."""
        item = dict(topic)
        m = re.match(r"https?://github\.com/([^/]+/[^/#?]+)", item.get("url") or "")
        if m:
            r = requests.get(f"https://api.github.com/repos/{m.group(1)}", headers=self.gh_headers, timeout=12)
            if r.status_code == 200:
                f = self._repo_item(r.json(), item.get("category") or "Trending GitHub")
                if f:
                    item.update({k: f[k] for k in ("stars", "language", "why_it_matters", "preview_image_url", "facts", "published_date", "description") if f.get(k)})
                    item["source"], item["source_kind"], item["title"] = "GitHub", "github", f["title"]
            elif r.status_code == 404:
                item["verification_status"] = "UNREACHABLE"
                item["verification_note"] = f"GitHub repo {m.group(1)} does not exist (404) — checked {ts()}"
                item["facts"] = []
                return item
        item["preview_image_url"] = item.get("preview_image_url") or ""
        return self.verify(item)


PRIORITY_MIN = 60


def priority(item: Dict[str, Any]) -> str:
    return "NEW" if item["opportunity_score"] >= PRIORITY_MIN and item.get("verification_status") == "VERIFIED" else "LOW_PRIORITY"


def rescore_library() -> int:
    """Re-apply the current scoring to untouched topics (no network). Converted/published/dismissed rows are left alone."""
    h, n = ResearchHarvester(), 0
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM topics WHERE status IN ('NEW','LOW_PRIORITY') AND source_kind!=''")]
        for r in rows:
            r["facts"] = json.loads(r.get("facts_json") or "[]")
            h.score(r)
            conn.execute("UPDATE topics SET opportunity_score=?, usefulness=?, relevance=?, suggested_format=?, suggested_slides=?, status=? WHERE id=?",
                         (r["opportunity_score"], r["usefulness"], r["relevance"], r["suggested_format"], r["suggested_slides"], priority(r), r["id"]))
            n += 1
    return n


def audience_for(category: str) -> str:
    return {
        "AI Industry News": "AI-curious professionals who want the signal, not the noise",
        "Trending GitHub": "Developers and builders looking for tools to try this week",
        "AI Developer Tools": "Software engineers adopting agents, MCP and AI coding tools",
        "AI Creator Tools": "Creators who want pro results without a studio",
        "Video & Animation": "Creators and editors making video with AI",
        "Open-Source Projects": "Builders who prefer open, self-hostable models",
        "Tutorials & Workflows": "Learners who want a step-by-step path",
    }.get(category, "AI builders and creators")


def recommend_format(item: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the smallest format that carries the verified material — never pad to 10."""
    facts = item.get("facts") or json.loads(item.get("facts_json") or "[]")
    cat = item.get("category", "")
    n_facts = len(facts) + (1 if item.get("description") else 0)
    if cat == "Video & Animation":
        return {"format": "REEL", "slides": 4, "reason": "Best shown as a screen-recorded demo Reel; 4-slide carousel as fallback."}
    if cat == "AI Industry News":
        if n_facts <= 2:
            return {"format": "SINGLE", "slides": 1, "reason": "One headline fact — a single image is enough."}
        return {"format": "CAROUSEL", "slides": 3, "reason": "News: what happened → why it matters → source."}
    if cat == "Tutorials & Workflows":
        return {"format": "CAROUSEL", "slides": min(8, 4 + n_facts // 2), "reason": "Step-by-step content needs room per step."}
    if n_facts >= 6:
        return {"format": "CAROUSEL", "slides": 5, "reason": "Rich verified detail: hook, what it is, proof, how to try, CTA."}
    return {"format": "CAROUSEL", "slides": 3, "reason": "Limited verified detail — keep it tight."}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from db.migrate_v2 import migrate
    migrate()
    res = ResearchHarvester().run_daily_harvest()
    for t in res[:10]:
        print(f"[{t['opportunity_score']}] [{t['category']}] [{t['verification_status']}] {t['title'][:70]}")

"""Quality control on the real carousel (slides, caption, hashtags, source). Score 0-100."""

import json
import re
from typing import Any, Dict, List

HYPE = ["mind-blowing", "insane", "game-changer", "game changer", "10x", "money glitch", "passive income", "you won't believe", "secret"]


class QualityControlEvaluator:
    def __init__(self, threshold: int = 85):
        self.threshold = threshold

    def evaluate(self, carousel: Dict[str, Any], topic: Dict[str, Any] = None, published_titles: List[str] = ()) -> Dict[str, Any]:
        topic = topic or {}
        data = carousel.get("slide_data") or json.loads(carousel.get("slide_data_json") or "{}")
        slides = data.get("slides", []) if isinstance(data, dict) else []
        caption = carousel.get("caption") or ""
        tags = (carousel.get("hashtags") or "").split()
        kw = (carousel.get("cta_keyword") or "").strip()
        checks = []

        def check(name, weight, ok, detail, partial=False):
            pts = weight if ok else (weight // 2 if partial else 0)
            checks.append({"name": name, "points": pts, "max": weight, "pass": ok, "detail": detail})

        n = len(slides)
        fmt = carousel.get("post_format", "CAROUSEL")
        check("Valid format", 10, (fmt == "SINGLE" and n == 1) or (fmt != "SINGLE" and 2 <= n <= 10),
              f"{n} slide(s) for {fmt}")
        words = [len(" ".join(str(s.get(k, "")) for k in ("title", "body")).split()) + sum(len(str(x).split()) for x in s.get("steps", []) + s.get("items", [])) for s in slides]
        mx = max(words or [0])
        check("Mobile legibility", 15, mx <= 45, f"Max {mx} words on a slide (≤45)", partial=mx <= 70)
        cover_title = (slides[0].get("title", "") if slides else "")
        check("Strong opening", 10, 3 <= len(cover_title) <= 60, f"Cover title {len(cover_title)} chars (3–60)", partial=bool(cover_title))
        pack = carousel.get("pack_topics") or []
        src_ok = all(t.get("verification_status") == "VERIFIED" for t in pack) if pack else topic.get("verification_status") == "VERIFIED"
        check("Verified source", 20, src_ok, topic.get("verification_note") or "Source not verified")
        has_img = any(s.get("image") or s.get("images") or s.get("tiles") for s in slides)
        check("Real imagery", 5, has_img, "Uses real screenshots / previews" if has_img else "No image on any slide", partial=n == 1)
        cta_ok = bool(kw) and (kw.lower() in caption.lower()) and any(s.get("keyword") == kw for s in slides) if n > 1 else bool(kw) and kw.lower() in caption.lower()
        check("CTA consistent", 10, cta_ok, f"Keyword '{kw}' in caption and CTA slide" if cta_ok else "Keyword missing from caption or CTA slide")
        check("Caption length", 10, 80 <= len(caption) <= 2200, f"{len(caption)} chars (80–2200)")
        check("Hashtags", 5, 3 <= len(tags) <= 15 and all(t.startswith("#") for t in tags), f"{len(tags)} hashtags (3–15)")
        hype = [h for h in HYPE if h in (caption + json.dumps(slides)).lower()]
        check("No hype language", 10, not hype, "Clean" if not hype else f"Found: {', '.join(hype)}")
        title_l = (carousel.get("headline") or "").lower()
        dup = any(title_l and (title_l in p.lower() or p.lower() in title_l) for p in published_titles if p)
        check("Not a repeat", 5, not dup, "Not previously published" if not dup else "Similar post already published")

        score = sum(c["points"] for c in checks)
        return {"score": score, "threshold": self.threshold, "passed": score >= self.threshold, "checks": checks}

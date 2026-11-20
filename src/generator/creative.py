"""SONU AI LAB creative engine.

Slide content is derived only from verified research fields (title, description, facts, README
install commands). The same HTML is used for the live Studio preview and for the exported JPG,
which is rendered by headless Edge/Chrome (one launch per deck) and cropped to 1080x1350.
"""

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from PIL import Image

W, H = 1080, 1350
UA = {"User-Agent": "SonuAILab-Creative/3.0"}

THEMES = {
    "studio": {"bg": "#F6F4F0", "bg2": "#E9EDFB", "ink": "#0B0D14", "muted": "#4A5064", "line": "rgba(11,13,20,.07)", "card": "rgba(255,255,255,.82)"},
    "midnight": {"bg": "#060A18", "bg2": "#0D1430", "ink": "#F5F7FF", "muted": "#A3ADCF", "line": "rgba(160,175,255,.16)", "card": "rgba(255,255,255,.04)"},
    "paper": {"bg": "#F4F2EC", "bg2": "#E9E6DD", "ink": "#0B0D14", "muted": "#555B6E", "line": "rgba(11,13,20,.12)", "card": "rgba(255,255,255,.7)"},
    "signal": {"bg": "#12062E", "bg2": "#2A0E5C", "ink": "#FFFFFF", "muted": "#C9B8F5", "line": "rgba(220,200,255,.2)", "card": "rgba(255,255,255,.06)"},
}
FONTS = {
    "grotesk": ("'Inter Tight', 'Segoe UI', sans-serif", 800, "-0.035em"),
    "serif": ("'Instrument Serif', Georgia, serif", 400, "-0.01em"),
    "mono": ("'JetBrains Mono', Consolas, monospace", 700, "-0.04em"),
}
DEFAULT_DESIGN = {"theme": "studio", "accent": "#4C7DFF", "font": "grotesk", "title_scale": 1.0, "show_handle": True}

HASHTAGS = {
    "AI Industry News": "#AINews #ArtificialIntelligence",
    "Trending GitHub": "#GitHub #OpenSource",
    "AI Developer Tools": "#DevTools #MCP #AIAgents",
    "AI Creator Tools": "#AIForCreators #ContentCreator",
    "Video & Animation": "#AIVideo #VideoEditing",
    "Open-Source Projects": "#OpenSource #HuggingFace",
    "Tutorials & Workflows": "#AITutorial #Workflow",
}
KICKERS = {
    "AI Industry News": "AI News", "Trending GitHub": "Trending on GitHub", "AI Developer Tools": "Dev Tool",
    "AI Creator Tools": "Creator Tool", "Video & Animation": "AI Video", "Open-Source Projects": "Open Source",
    "Tutorials & Workflows": "Workflow",
}
INSTALL_RE = re.compile(r"^\s*(?:\$\s*)?((?:pip3?|pipx|uv pip|uv tool|npm|pnpm|yarn|bun|brew|cargo|go|conda|winget|apt(?:-get)?|sudo apt(?:-get)?)\s+(?:install|i|add|get)\b.*|git clone\b.*|(?:npx|uvx|bunx|pipx run)\s+\S.*|docker (?:run|pull)\b.*|cargo run\b.*|uv (?:sync|add)\b.*|curl\s.*\|\s*(?:sh|bash)\b.*|irm\s.*\|\s*iex.*)$", re.I)


# ------------------------------------------------------------------ research → slides

IMG_MD = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
IMG_HTML = re.compile(r"<img[^>]+src=[\"']([^\"']+)", re.I)
BADGE = re.compile(r"shields\.io|badge|travis-ci|codecov|star-history|contrib\.rocks|api\.star|visitor|hits\.|komarev|\.svg(\?|$)|logo|icon|[-_]mark[-_.]|avatar|sponsor|discord|twitter|wechat|qr", re.I)


def _readme(url: str):
    m = re.match(r"https?://github\.com/([^/]+/[^/#?]+)", url or "")
    h = re.match(r"https?://huggingface\.co/([^/]+/[^/#?]+)", url or "")
    try:
        if m:
            r = requests.get(f"https://api.github.com/repos/{m.group(1)}/readme",
                             headers={**UA, "Accept": "application/vnd.github.raw"}, timeout=10)
            base = f"https://raw.githubusercontent.com/{m.group(1)}/HEAD/"
        elif h:
            r = requests.get(f"https://huggingface.co/{h.group(1)}/raw/main/README.md", headers=UA, timeout=10)
            base = f"https://huggingface.co/{h.group(1)}/resolve/main/"
        else:
            return None, ""
        return (r.text if r.status_code == 200 else None), base
    except Exception:
        return None, ""


def _is_image(u: str) -> bool:
    """A real screenshot: raster image, at least 480px wide, not a banner/logo strip (aspect between 0.45 and 2.6)."""
    import io
    try:
        r = requests.get(u, headers=UA, timeout=8, stream=True)
        if r.status_code >= 400 or not r.headers.get("content-type", "").startswith("image/") or "svg" in r.headers.get("content-type", ""):
            return False
        head = b""
        for chunk in r.iter_content(16384):
            head += chunk
            if len(head) >= 65536:
                break
        r.close()
        w, h = Image.open(io.BytesIO(head)).size
        return w >= 480 and 0.45 <= w / max(h, 1) <= 2.6
    except Exception:
        return False


def fetch_readme(url: str) -> Dict[str, List[str]]:
    """Real material from the project's README: install commands, product screenshots, feature bullets."""
    text, base = _readme(url)
    out = {"install": [], "images": [], "features": []}
    if not text:
        return out
    in_code = False
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            mm = INSTALL_RE.match(line)
            cmd = re.sub(r"\s+#.*$", "", mm.group(1)).strip() if mm else ""
            if cmd and len(cmd) <= 90 and cmd not in out["install"] and len(out["install"]) < 4:
                out["install"].append(cmd)
        elif re.match(r"^[-*] ", st) and len(out["features"]) < 6:
            f = re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>", "", st[2:])        # images / html
            f = re.sub(r"\[([^\]]+)\]\([^)]*\)", lambda mm: mm.group(1), f)  # links -> text
            f = re.sub(r"[*_`]+|^\[[ xX]\]\s*", "", f).strip(" :-")
            low = f.lower()
            skip = ("thank", "discord", "sponsor", "contributor", "star us", "wechat", "license", "integration")
            if 18 <= len(f) <= 110 and not low.startswith(("http", "see ", "check ")) \
                    and not re.match(r"^\W*\[?\d{4}|^\W*[a-z]{3,9}\.? \d{1,2},? \d{4}", low) and not any(w in low for w in skip) and "@" not in f:
                out["features"].append(f)
    cands = []
    for u in IMG_MD.findall(text) + IMG_HTML.findall(text):
        u = u.strip()
        if BADGE.search(u):
            continue
        if not u.startswith("http"):
            u = base + u.lstrip("./")
        if u not in cands:
            cands.append(u)
    for u in cands[:8]:
        if _is_image(u):
            out["images"].append(u)
        if len(out["images"]) >= 3:
            break
    return out


def fetch_install_steps(url: str) -> List[str]:
    return fetch_readme(url)["install"]


def _split_fact(f: str):
    """'12,345 GitHub stars' → ('12,345', 'GitHub stars'); 'License: MIT' → ('MIT', 'License')."""
    m = re.match(r"^([\d,.]+[kKmM]?)\s+(.*)$", f)
    if m:
        return m.group(1), m.group(2)
    if ":" in f:
        k, v = f.split(":", 1)
        return v.strip(), k.strip()
    m = re.match(r"^(Created|Released|Published|Last commit|Written in)\s+(.*)$", f)
    if m:
        return m.group(2), m.group(1)
    return f, ""


def display_title(topic: Dict[str, Any]) -> str:
    t = topic.get("title", "")
    if topic.get("source_kind") in ("github", "hf") and "/" in t and " " not in t:
        return t.split("/", 1)[1]
    return t


def build_slides(topic: Dict[str, Any], n: int, install: Optional[List[str]] = None, keyword: str = "AGENT",
                 resource_items: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Build up to n slides. Only material that exists is used, so fewer slides may come back."""
    facts = topic.get("facts") or json.loads(topic.get("facts_json") or "[]")
    cat = topic.get("category", "")
    desc = (topic.get("description") or "").strip()
    img = topic.get("preview_image_url") or ""
    title = display_title(topic)
    owner = topic["title"].split("/")[0] if "/" in topic.get("title", "") and " " not in topic["title"] else topic.get("source", "")

    cover = {"layout": "cover", "kicker": KICKERS.get(cat, "AI"), "title": title,
             "body": desc[:150], "image": img, "meta": f"{owner} · {topic.get('published_date', '')}".strip(" ·")}
    pool = []
    has_what = bool(desc and len(desc) > 60 and n >= 3)
    if has_what:
        pool.append({"layout": "point", "kicker": "What it is", "title": title, "body": desc[:300]})
        # cover gets the momentum line instead of repeating the description
        cover["body"] = topic.get("why_it_matters") or ""
    if len(facts) >= 2:
        pool.append({"layout": "facts", "kicker": "The numbers", "title": "Verified at the source",
                     "facts": [list(_split_fact(f)) for f in facts[:4]]})
    if install:
        short = re.sub(r"^https?://(www\.)?", "", topic.get("url", ""))
        pool.append({"layout": "steps", "kicker": "Try it", "title": "Get started in minutes",
                     "steps": install[:4], "body": f"Full setup: {short}"})
    if topic.get("why_it_matters") and not has_what:
        pool.append({"layout": "point", "kicker": "Why it matters", "title": "Why people are paying attention",
                     "body": topic["why_it_matters"]})
    if img and n >= 6:
        pool.append({"layout": "image", "kicker": "Look inside", "title": title, "image": img,
                     "body": f"Source: {topic.get('url', '')}"})
    cta = {"layout": "cta", "kicker": "Get the pack", "keyword": keyword,
           "title": f"Comment {keyword}", "body": "and I'll send you the links in your DMs",
           "items": (resource_items or ["Direct source link", "Quick-start steps" if install else "Key facts"])[:3]}

    if n <= 1:
        cover["layout"] = "single"
        cover["facts"] = [list(_split_fact(f)) for f in facts[:2]]
        return [cover]
    middle = pool[: max(0, n - 2)]
    return [cover, *middle, cta]


def regenerate_slide(slide: Dict[str, Any], topic: Dict[str, Any]) -> Dict[str, Any]:
    """Alternate treatment of the same verified material (layout / emphasis swap)."""
    s = dict(slide)
    alt = {"point": "quote", "quote": "point", "facts": "facts_list", "facts_list": "facts",
           "cover": "cover_type", "cover_type": "cover", "steps": "steps", "image": "point", "cta": "cta_minimal",
           "cta_minimal": "cta", "single": "single"}
    s["layout"] = alt.get(s.get("layout"), s.get("layout"))
    if s["layout"] == "point" and slide.get("layout") == "image":
        s["body"] = topic.get("description") or s.get("body", "")
    return s


def build_caption(topic: Dict[str, Any], keyword: str) -> str:
    desc = (topic.get("description") or "").strip()
    parts = [display_title(topic) if topic.get("source_kind") != "hn" else topic["title"]]
    if desc:
        parts.append(desc[:280])
    if topic.get("why_it_matters"):
        parts.append(f"Why it matters: {topic['why_it_matters']}")
    parts.append(f"Source: {topic.get('url', '')}")
    parts.append(f"Comment \"{keyword}\" and I'll DM you the link + quick-start.\nSave this so you can find it later.")
    return "\n\n".join(parts)


def build_hashtags(topic: Dict[str, Any], defaults: str) -> str:
    tags = (HASHTAGS.get(topic.get("category", ""), "") + " " + (defaults or "")).split()
    return " ".join(dict.fromkeys(tags))[:300]


def build_resource_pack(topic: Dict[str, Any], install: List[str]) -> str:
    lines = [f"{display_title(topic)}", f"Source: {topic.get('url', '')}"]
    if install:
        lines.append("Quick start:")
        lines += [f"  {c}" for c in install]
    disc = next((f for f in json.loads(topic.get("facts_json") or "[]") if f.startswith("Discussion:")), "")
    if disc:
        lines.append(disc)
    return "\n".join(lines)


# ------------------------------------------------------------------ HTML

def _e(s) -> str:
    return html.escape(str(s or ""))


def _title_size(text: str, base: int, scale: float) -> int:
    n = len(text or "")
    size = base if n < 24 else base * 0.82 if n < 44 else base * 0.66 if n < 70 else base * 0.54
    return int(size * scale)


def slide_css(design: Dict[str, Any]) -> str:
    d = {**DEFAULT_DESIGN, **(design or {})}
    t = THEMES.get(d["theme"], THEMES["midnight"])
    ff, fw, ls = FONTS.get(d["font"], FONTS["grotesk"])
    acc = d["accent"] if re.match(r"^#[0-9a-fA-F]{6}$", str(d["accent"])) else "#4C7DFF"
    return f"""
:root{{--bg:{t['bg']};--bg2:{t['bg2']};--ink:{t['ink']};--muted:{t['muted']};--line:{t['line']};--card:{t['card']};--acc:{acc};
--tf:{ff};--tw:{fw};--tl:{ls}}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#000;font-family:'Inter','Segoe UI',sans-serif;color:var(--ink)}}
.s{{position:relative;width:{W}px;height:{H}px;overflow:hidden;background:
 radial-gradient(900px 700px at 85% -10%, color-mix(in srgb,var(--acc) 30%,transparent), transparent 60%),
 radial-gradient(800px 600px at -10% 110%, color-mix(in srgb,var(--acc) 14%,transparent), transparent 60%),
 linear-gradient(180deg,var(--bg),var(--bg2));padding:88px 84px;display:flex;flex-direction:column}}
.s::before{{content:"";position:absolute;inset:0;background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
 background-size:90px 90px;mask-image:radial-gradient(ellipse at 70% 20%,#000 0%,transparent 65%);opacity:.55;pointer-events:none}}
.top{{display:flex;justify-content:space-between;align-items:center;font:600 22px 'JetBrains Mono',Consolas,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);position:relative}}
.brand{{display:flex;align-items:center;gap:14px;color:var(--ink)}}
.brand i{{width:16px;height:16px;border-radius:50%;background:var(--acc);box-shadow:0 0 24px var(--acc)}}
.kicker{{display:inline-flex;align-self:flex-start;gap:12px;align-items:center;font:600 24px 'JetBrains Mono',Consolas,monospace;letter-spacing:.1em;text-transform:uppercase;
 color:var(--acc);border:1.5px solid color-mix(in srgb,var(--acc) 55%,transparent);padding:12px 22px;border-radius:999px;margin-top:64px;position:relative}}
h1{{font-family:var(--tf);font-weight:var(--tw);letter-spacing:var(--tl);line-height:.98;margin-top:34px;position:relative;overflow-wrap:anywhere}}
h1 em{{font-style:normal;color:var(--acc)}}
.body{{font-size:38px;line-height:1.38;color:var(--muted);margin-top:34px;max-width:880px;position:relative}}
.foot{{margin-top:auto;display:flex;justify-content:space-between;align-items:center;font:500 22px 'JetBrains Mono',Consolas,monospace;color:var(--muted);position:relative;
 border-top:1px solid var(--line);padding-top:28px}}
.swipe{{color:var(--ink)}}
.img{{margin-top:auto;border-radius:28px;overflow:hidden;border:1px solid var(--line);background:var(--card);position:relative;flex:0 1 auto;min-height:0;
 box-shadow:0 40px 80px -30px rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center}}
.img+.foot,.img+.body{{margin-top:36px}}
.facts+.foot,.steps+.foot,.flist+.foot{{margin-top:0}}
.steps.few{{margin-top:70px;margin-bottom:0}}
.steps .step code{{font-size:32px}}
.img img{{width:100%;height:auto;max-height:640px;object-fit:contain;display:block}}
.ghost{{position:absolute;right:84px;bottom:120px;font:800 360px/1 'Inter Tight',sans-serif;letter-spacing:-.06em;color:transparent;
 -webkit-text-stroke:2px var(--line);pointer-events:none}}
.body.big{{font-size:56px;line-height:1.22;color:var(--ink);font-weight:500;letter-spacing:-.01em}}
.num{{font:700 30px 'JetBrains Mono',monospace;color:var(--acc);position:relative;margin-top:60px}}
.facts{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:auto;margin-bottom:44px;position:relative}}
.fact{{background:var(--card);border:1px solid var(--line);border-radius:28px;padding:40px 36px;min-height:230px;display:flex;flex-direction:column;justify-content:space-between}}
.fact b{{font-family:var(--tf);font-weight:var(--tw);font-size:64px;letter-spacing:-.03em;line-height:1;overflow-wrap:anywhere}}
.fact span{{font-size:26px;color:var(--muted);margin-top:18px}}
.flist{{margin-top:auto;margin-bottom:30px;position:relative}}
.flist div{{display:flex;justify-content:space-between;gap:30px;font-size:36px;padding:28px 0;border-bottom:1px solid var(--line)}}
.flist div span{{color:var(--muted)}}
.steps{{margin-top:auto;margin-bottom:44px;display:flex;flex-direction:column;gap:20px;position:relative}}
.step{{display:flex;gap:26px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:24px;padding:28px 30px}}
.step i{{font:700 26px 'JetBrains Mono',monospace;color:var(--acc);font-style:normal;min-width:44px}}
.step code{{font:500 30px 'JetBrains Mono',Consolas,monospace;color:var(--ink);overflow-wrap:anywhere}}
.quote{{font-family:var(--tf);font-weight:var(--tw);font-size:64px;line-height:1.12;letter-spacing:-.02em;margin-top:60px;position:relative}}
.quote::before{{content:"";display:block;width:90px;height:8px;background:var(--acc);border-radius:8px;margin-bottom:44px}}
.kw{{display:inline-block;font-family:var(--tf);font-weight:var(--tw);font-size:150px;letter-spacing:-.04em;color:#fff;background:var(--acc);
 padding:10px 46px 22px;border-radius:36px;margin-top:30px;box-shadow:0 30px 90px -20px var(--acc);position:relative;line-height:1.05}}
.items{{margin-top:64px;display:flex;flex-direction:column;gap:18px;position:relative}}
.items div{{font-size:36px;display:flex;gap:20px;align-items:center}}
.items div::before{{content:"";width:14px;height:14px;border-radius:50%;background:var(--acc)}}
.cover-type h1{{margin-top:auto}}
""" + SHOWCASE_CSS


def slide_inner(s: Dict[str, Any], idx: int, total: int, design: Dict[str, Any], handle: str, brand: str) -> str:
    d = {**DEFAULT_DESIGN, **(design or {})}
    sc = float(d.get("title_scale") or 1)
    L = s.get("layout", "point")
    if L in SHOWCASE_LAYOUTS:
        return showcase_inner(s, idx, total, d, handle, brand)
    top = f'<div class="top"><div class="brand"><i></i>{_e(brand)}</div><div>{idx:02d} / {total:02d}</div></div>'
    foot_r = '<span class="swipe">Swipe →</span>' if idx < total else '<span>Save · Share</span>'
    foot = f'<div class="foot"><span>{_e(handle) if d.get("show_handle", True) else ""}</span>{foot_r}</div>'
    kicker = f'<div class="kicker">{_e(s.get("kicker"))}</div>' if s.get("kicker") else ""
    title = s.get("title", "")

    def img_block(src):
        return f'<div class="img"><img src="{_e(src)}" referrerpolicy="no-referrer"></div>' if src else ""

    if L in ("cover", "single"):
        body = f'<p class="body">{_e(s.get("body"))}</p>' if s.get("body") else ""
        extra = ""
        if L == "single" and s.get("facts"):
            extra = '<div class="facts">' + "".join(f'<div class="fact"><b>{_e(v)}</b><span>{_e(k)}</span></div>' for v, k in s["facts"]) + "</div>"
        meta = f'<div class="foot"><span>{_e(s.get("meta"))}</span>{foot_r}</div>'
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 128, sc)}px">{_e(title)}</h1>{body}{extra or img_block(s.get("image"))}{meta}'
    elif L == "cover_type":
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 150, sc)}px">{_e(title)}</h1><p class="body">{_e(s.get("body"))}</p><div class="foot"><span>{_e(s.get("meta"))}</span>{foot_r}</div>'
    elif L == "facts":
        tiles = "".join(f'<div class="fact"><b>{_e(v)}</b><span>{_e(k)}</span></div>' for v, k in s.get("facts", []))
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 96, sc)}px">{_e(title)}</h1><div class="facts">{tiles}</div>{foot}'
    elif L == "facts_list":
        rows = "".join(f'<div><span>{_e(k)}</span><b>{_e(v)}</b></div>' for v, k in s.get("facts", []))
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 96, sc)}px">{_e(title)}</h1><div class="flist">{rows}</div>{foot}'
    elif L == "steps":
        steps = "".join(f'<div class="step"><i>{i:02d}</i><code>{_e(c)}</code></div>' for i, c in enumerate(s.get("steps", []), 1))
        few = " few" if len(s.get("steps", [])) < 3 else ""
        note = f'<p class="body" style="font-size:30px;margin-top:28px">{_e(s.get("body"))}</p>' if s.get("body") else ""
        stage = _cards(s.get("images", [])[:1]) if s.get("images") else ""
        if stage:
            foot = foot.replace('class="foot"', 'class="foot" style="margin-top:30px"')
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 96, sc)}px">{_e(title)}</h1><div class="steps{few}">{steps}</div>{note}{stage}{foot}'
    elif L == "image":
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 80, sc)}px">{_e(title)}</h1>{img_block(s.get("image"))}<p class="body" style="font-size:26px">{_e(s.get("body"))}</p>{foot}'
    elif L == "quote":
        inner = f'{top}{kicker}<div class="quote" style="font-size:{int(64 * sc)}px">{_e(s.get("body"))}</div>{foot}'
    elif L in ("cta", "cta_minimal"):
        items = "" if L == "cta_minimal" else '<div class="items">' + "".join(f"<div>{_e(i)}</div>" for i in s.get("items", [])) + "</div>"
        inner = (f'{top}{kicker}<h1 style="font-size:{int(84 * sc)}px">Comment</h1><div><span class="kw">{_e(s.get("keyword"))}</span></div>'
                 f'<p class="body">{_e(s.get("body"))}</p>{items}{foot}')
    else:  # point
        inner = (f'{top}{kicker}<h1 style="font-size:{_title_size(title, 100, sc)}px">{_e(title)}</h1>'
                 f'<p class="body{" big" if len(s.get("body") or "") < 160 else ""}" style="font-size:{56 if len(s.get("body") or "") < 160 else 42}px">{_e(s.get("body"))}</p>{img_block(s.get("image"))}{foot}')
    if L in ("point", "quote", "facts_list") and not s.get("image"):
        inner = f'<div class="ghost">{idx:02d}</div>' + inner
    cls = "s cover-type" if L == "cover_type" else "s"
    return f'<section class="{cls}">{inner}</section>'


FONT_LINK = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Inter+Tight:wght@600;800'
             '&family=Instrument+Serif&family=JetBrains+Mono:wght@500;600;700&display=block" rel="stylesheet">')


def slide_document(slides: List[Dict[str, Any]], design: Dict[str, Any], handle: str, brand: str,
                   only: Optional[int] = None) -> str:
    total = len(slides)
    secs = [slide_inner(s, i, total, design, handle, brand) for i, s in enumerate(slides, 1) if only is None or i == only]
    return (f'<!doctype html><html><head><meta charset="utf-8">{FONT_LINK}<style>{slide_css(design)}'
            f'html,body{{width:{W}px;overflow:hidden}}</style></head><body>{"".join(secs)}</body></html>')


# ------------------------------------------------------------------ headless render

def find_browser() -> Optional[str]:
    for p in [os.getenv("CMS_BROWSER"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("chromium"), shutil.which("google-chrome")]:
        if p and Path(p).exists():
            return p
    return None


def render_to_jpgs(doc_html: str, count: int, out_dir: Path, names: List[str]) -> List[Path]:
    """Screenshot a stacked document of `count` slides with one browser launch, crop into JPGs."""
    browser = find_browser()
    if not browser:
        raise RuntimeError("No Edge/Chrome found for slide rendering (set CMS_BROWSER).")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src, png = Path(tmp) / "deck.html", Path(tmp) / "deck.png"
        src.write_text(doc_html, encoding="utf-8")
        cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--force-device-scale-factor=1", f"--user-data-dir={Path(tmp) / 'profile'}",
               "--virtual-time-budget=8000", f"--window-size={W},{H * count}", f"--screenshot={png}", src.as_uri()]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if not png.exists():
            raise RuntimeError("Browser did not produce a screenshot.")
        sheet = Image.open(png).convert("RGB")
        paths = []
        for i, name in enumerate(names):
            p = out_dir / name
            sheet.crop((0, i * H, W, (i + 1) * H)).save(p, "JPEG", quality=92, optimize=True)
            paths.append(p)
        return paths


# ------------------------------------------------------------------ 3D showcase layouts (Studio theme default)
# Real screenshots (README images, else the source's preview card) on perspective-tilted cards.

SHOWCASE_LAYOUTS = {"cover3d", "showcase", "pack_cover", "features"}

SHOWCASE_CSS = """
.stage{flex:1;position:relative;margin-top:36px;perspective:2600px;min-height:0}
.stage::after{content:"";position:absolute;left:12%;right:12%;bottom:-6px;height:60px;border-radius:50%;
 background:radial-gradient(ellipse at center,rgba(10,14,40,.28),transparent 70%);filter:blur(10px)}
.c3{position:absolute;border-radius:24px;overflow:hidden;background:#fff;transform-style:preserve-3d;
 box-shadow:0 60px 100px -36px rgba(12,16,48,.55),0 0 0 9px rgba(255,255,255,.95),0 0 0 10px rgba(10,14,40,.08)}
.c3 img{width:100%;height:100%;object-fit:cover;object-position:top center;display:block}
.c3.solo{left:7%;right:7%;top:3%;bottom:12%;transform:rotateX(14deg) rotateY(-16deg) rotateZ(2.5deg)}
.c3.a{left:16%;right:4%;top:0;bottom:22%;transform:rotateX(12deg) rotateY(-18deg) rotateZ(3deg) translateZ(40px);z-index:3}
.c3.b{left:0;right:34%;top:22%;bottom:4%;transform:rotateX(10deg) rotateY(14deg) rotateZ(-4deg) translateZ(-60px);z-index:2}
.c3.c{left:44%;right:0;top:38%;bottom:0;transform:rotateX(8deg) rotateY(-10deg) rotateZ(5deg) translateZ(-120px);z-index:1}
.bignum{font:800 150px/0.9 'Inter Tight',sans-serif;letter-spacing:-.06em;color:var(--acc);margin-top:54px;position:relative}
.chips{display:flex;gap:14px;flex-wrap:wrap;margin-top:28px;position:relative}
.chips span{font:600 24px 'Inter',sans-serif;padding:12px 22px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--ink)}
.grid6{display:grid;grid-template-columns:1fr 1fr;gap:34px 30px;margin-top:44px;flex:1;perspective:2200px;position:relative}
.tile{display:flex;flex-direction:column;gap:14px;min-height:0}
.tile .c3{position:relative;flex:1;min-height:0;transform:rotateX(10deg) rotateY(-10deg) rotateZ(1.5deg)}
.tile:nth-child(even) .c3{transform:rotateX(10deg) rotateY(10deg) rotateZ(-1.5deg)}
.tile b{font:700 28px 'Inter Tight',sans-serif;letter-spacing:-.01em}
.tile b i{font-style:normal;color:var(--acc);margin-right:10px}
.feat{margin-top:auto;margin-bottom:40px;display:grid;gap:18px;position:relative}
.feat div{display:flex;gap:22px;align-items:flex-start;font-size:34px;line-height:1.3;background:var(--card);border:1px solid var(--line);border-radius:24px;padding:26px 30px}
.feat div i{font:700 26px 'JetBrains Mono',monospace;font-style:normal;color:var(--acc);padding-top:6px;min-width:44px}
"""


def _cards(images: List[str]) -> str:
    imgs = [u for u in images if u][:3]
    if not imgs:
        return ""
    if len(imgs) == 1:
        return f'<div class="stage"><div class="c3 solo"><img src="{_e(imgs[0])}" referrerpolicy="no-referrer"></div></div>'
    return '<div class="stage">' + "".join(f'<div class="c3 {k}"><img src="{_e(u)}" referrerpolicy="no-referrer"></div>'
                                          for k, u in zip("abc", imgs)) + "</div>"


def showcase_inner(s: Dict[str, Any], idx: int, total: int, d: Dict[str, Any], handle: str, brand: str) -> str:
    sc = float(d.get("title_scale") or 1)
    L, title = s["layout"], s.get("title", "")
    top = f'<div class="top"><div class="brand"><i></i>{_e(brand)}</div><div>{idx:02d} / {total:02d}</div></div>'
    foot_r = '<span class="swipe">Swipe →</span>' if idx < total else '<span>Save · Share</span>'
    left = s.get("meta") if L == "cover3d" else (handle if d.get("show_handle", True) else "")
    foot = f'<div class="foot" style="margin-top:34px"><span>{_e(left)}</span>{foot_r}</div>'
    kicker = f'<div class="kicker">{_e(s.get("kicker"))}</div>' if s.get("kicker") else ""
    if L == "cover3d":
        body = f'<p class="body" style="margin-top:22px">{_e(s.get("body"))}</p>' if s.get("body") else ""
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 120, sc)}px">{_e(title)}</h1>{body}{_cards(s.get("images", []))}{foot}'
    elif L == "showcase":
        chips = '<div class="chips">' + "".join(f"<span>{_e(c)}</span>" for c in s.get("chips", [])[:4]) + "</div>" if s.get("chips") else ""
        body = f'<p class="body" style="margin-top:18px;font-size:34px">{_e(s.get("body"))}</p>' if s.get("body") else ""
        inner = (f'{top}<div class="bignum">{_e(s.get("num") or f"{idx - 1:02d}")}</div>'
                 f'<h1 style="font-size:{_title_size(title, 88, sc)}px;margin-top:18px">{_e(title)}</h1>{body}{chips}{_cards(s.get("images", [])[:1])}{foot}')
    elif L == "pack_cover":
        tiles = "".join(f'<div class="tile"><div class="c3"><img src="{_e(t.get("image"))}" referrerpolicy="no-referrer"></div>'
                        f'<b><i>{i:02d}</i>{_e(t.get("name"))}</b></div>' for i, t in enumerate(s.get("tiles", [])[:6], 1))
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 104, sc)}px">{_e(title)}</h1><div class="grid6">{tiles}</div>{foot}'
    else:  # features
        rows = "".join(f'<div><i>{i:02d}</i><span>{_e(f)}</span></div>' for i, f in enumerate(s.get("features", [])[:5], 1))
        inner = f'{top}{kicker}<h1 style="font-size:{_title_size(title, 92, sc)}px">{_e(title)}</h1><div class="feat">{rows}</div>{foot}'
    return f'<section class="s">{inner}</section>'


def _chips(topic: Dict[str, Any]) -> List[str]:
    out = []
    if topic.get("source_kind") == "github" and topic.get("stars"):
        out.append(f"★ {topic['stars']:,}")
    if topic.get("source_kind") == "hf" and topic.get("stars"):
        out.append(f"♥ {topic['stars']:,} likes")
    if topic.get("language"):
        out.append(topic["language"])
    if topic.get("cost_type") in ("Open Source", "Open weights"):
        out.append("Free · " + topic["cost_type"])
    return out


def topic_images(topic: Dict[str, Any], readme: Optional[Dict[str, List[str]]]) -> List[str]:
    imgs = list((readme or {}).get("images") or [])
    if topic.get("preview_image_url") and topic["preview_image_url"] not in imgs:
        imgs.append(topic["preview_image_url"])
    return imgs


def build_slides_v2(topic: Dict[str, Any], n: int, readme: Dict[str, List[str]], keyword: str) -> List[Dict[str, Any]]:
    """3D showcase deck for one tool. Uses only verified fields + real README material; never padded."""
    if n <= 1:
        return build_slides(topic, 1, readme.get("install"), keyword)
    imgs = topic_images(topic, readme)
    desc = (topic.get("description") or "").strip()
    title = display_title(topic)
    owner = topic["title"].split("/")[0] if "/" in topic.get("title", "") and " " not in topic["title"] else topic.get("source", "")
    cover = {"layout": "cover3d", "kicker": KICKERS.get(topic.get("category", ""), "AI"), "title": title,
             "body": desc[:120] if desc else topic.get("why_it_matters", ""), "images": imgs[:3],
             "meta": f"{owner} · {topic.get('published_date', '')}".strip(" ·")}
    pool = []
    shots = (readme.get("images") or [])
    if shots:
        pool.append({"layout": "showcase", "num": "01", "title": "See it in action", "body": topic.get("why_it_matters") or "",
                     "chips": _chips(topic), "images": [shots[1] if len(shots) > 1 else shots[0]]})
    elif desc and len(desc) > 60:
        pool.append({"layout": "point", "kicker": "What it is", "title": title, "body": desc[:300]})
    if len(readme.get("features") or []) >= 3:
        pool.append({"layout": "features", "kicker": "What you can do", "title": "Why it's worth trying", "features": readme["features"][:5]})
    if readme.get("install"):
        short = re.sub(r"^https?://(www\.)?", "", topic.get("url", ""))
        pool.append({"layout": "steps", "kicker": "Try it", "title": "Get started in minutes", "steps": readme["install"][:4],
                     "body": f"Full setup: {short}", "images": imgs[-1:] if len(readme["install"]) < 3 else []})
    facts = topic.get("facts") or json.loads(topic.get("facts_json") or "[]")
    if len(facts) >= 2:
        pool.append({"layout": "facts", "kicker": "The numbers", "title": "Verified at the source", "facts": [list(_split_fact(f)) for f in facts[:4]]})
    cta = {"layout": "cta", "kicker": "Free guide", "keyword": keyword, "title": f"Comment {keyword}",
           "body": "and I'll DM you the full step-by-step guide",
           "items": ["Install steps you can copy", "Screenshots of what it does", "Direct link"]}
    return [cover, *pool[: max(0, n - 2)], cta]


PACK_NOUN = {"Video & Animation": "AI video tools", "AI Creator Tools": "AI tools for creators", "AI Developer Tools": "AI dev tools",
             "Trending GitHub": "trending AI repos", "Open-Source Projects": "open-source AI models", "Tutorials & Workflows": "AI learning resources",
             "AI Industry News": "AI stories"}


def pack_title(topics: List[Dict[str, Any]]) -> str:
    cats = {t.get("category") for t in topics}
    noun = PACK_NOUN.get(cats.pop(), "AI tools") if len(cats) == 1 else "AI tools"
    free = all(t.get("cost_type") in ("Open Source", "Open weights") for t in topics)
    return f"{len(topics)} {'free ' if free else ''}{noun} trending this week"


def build_pack(items: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
    """items: [{"topic":…, "readme":…}] → cover grid + one showcase per tool + CTA (max 10 slides)."""
    items = items[:8]
    topics = [it["topic"] for it in items]
    tiles = [{"name": display_title(t), "image": (topic_images(t, it["readme"]) or [""])[0]} for t, it in zip(topics, items)]
    slides = [{"layout": "pack_cover", "kicker": "Save this pack", "title": pack_title(topics), "tiles": tiles}]
    for i, it in enumerate(items, 1):
        t, r = it["topic"], it["readme"]
        slides.append({"layout": "showcase", "num": f"{i:02d}", "title": display_title(t),
                       "body": (t.get("description") or t.get("why_it_matters") or "")[:130], "chips": _chips(t),
                       "images": topic_images(t, r)[:1]})
    slides.append({"layout": "cta", "kicker": "Free guide", "keyword": keyword, "title": f"Comment {keyword}",
                   "body": f"and I'll DM you the setup guide for all {len(items)}",
                   "items": ["Install steps for every tool", "Screenshots", "Direct links"]})
    return slides


def pack_caption(items: List[Dict[str, Any]], keyword: str) -> str:
    lines = [pack_title([it["topic"] for it in items]) + " 👇", ""]
    for i, it in enumerate(items, 1):
        t = it["topic"]
        lines.append(f"{i}. {display_title(t)} — {(t.get('description') or '')[:90]}")
    lines += ["", f"Comment \"{keyword}\" and I'll DM you the full setup guide for all of them.", "Save this so you can find it later."]
    return "\n".join(lines)


# ------------------------------------------------------------------ DM guide document (rendered to images, sent in the DM)

GUIDE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#000;font-family:'Inter','Segoe UI',sans-serif}
.g{width:1080px;height:1350px;overflow:hidden;background:#FBFAF7;color:#0B0D14;padding:72px 76px;display:flex;flex-direction:column;position:relative}
.g::before{content:"";position:absolute;inset:0 0 auto 0;height:14px;background:linear-gradient(90deg,#4C7DFF,#8B5CF6,#3BE0FF)}
.gh{display:flex;justify-content:space-between;font:600 21px 'JetBrains Mono',monospace;letter-spacing:.08em;text-transform:uppercase;color:#6A7085}
.g h1{font:800 72px/1.02 'Inter Tight',sans-serif;letter-spacing:-.035em;margin-top:30px;overflow-wrap:anywhere}
.g h2{font:700 30px 'Inter Tight',sans-serif;margin-top:34px;display:flex;gap:14px;align-items:center}
.g h2 i{font-style:normal;width:44px;height:44px;border-radius:12px;background:#4C7DFF;color:#fff;display:grid;place-items:center;font-size:22px}
.g p{font-size:30px;line-height:1.42;color:#33384A;margin-top:16px}
.shot{margin-top:26px;border-radius:20px;overflow:hidden;border:1px solid #E3E1DA;box-shadow:0 30px 60px -30px rgba(10,14,40,.35);background:#fff;flex:0 1 auto;min-height:0;max-height:520px}
.shot img{width:100%;height:100%;max-height:520px;object-fit:contain;display:block;background:#fff}
pre{margin-top:16px;background:#0D1120;color:#E8ECFF;border-radius:18px;padding:22px 26px;font:500 25px/1.6 'JetBrains Mono',Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.fl{margin-top:14px;display:grid;gap:10px}
.fl div{font-size:27px;line-height:1.35;padding-left:34px;position:relative;color:#262A3A}
.fl div::before{content:"✓";position:absolute;left:0;color:#4C7DFF;font-weight:800}
.link{margin-top:28px;padding-top:24px;border-top:1px solid #E3E1DA;font:600 24px 'JetBrains Mono',monospace;color:#3557D6;overflow-wrap:anywhere}
.toc{margin-top:30px;display:grid;gap:16px}
.toc div{display:flex;gap:22px;align-items:center;font-size:34px;font-weight:600;padding:22px 26px;border-radius:18px;background:#fff;border:1px solid #E7E5DF}
.toc div i{font:700 26px 'JetBrains Mono',monospace;font-style:normal;color:#4C7DFF}
"""


def guide_pages(items: List[Dict[str, Any]], brand: str, handle: str) -> List[str]:
    """One or two pages per tool: overview (+screenshot) and setup (install + features + link). Pack gets an index page."""
    pages, total_tools = [], len(items)
    if total_tools > 1:
        toc = "".join(f'<div><i>{i:02d}</i>{_e(display_title(it["topic"]))}</div>' for i, it in enumerate(items, 1))
        pages.append(f'<h1>{_e(pack_title([it["topic"] for it in items]))}</h1><p>Your step-by-step guide. Each tool has its own page with what it does, how to install it and the link.</p><div class="toc">{toc}</div>')
    for i, it in enumerate(items, 1):
        t, r = it["topic"], it["readme"] or {}
        name, desc = display_title(t), (t.get("description") or "").strip()
        imgs = topic_images(t, r)
        num = f"Tool {i:02d} · " if total_tools > 1 else ""
        shot = f'<div class="shot"><img src="{_e(imgs[0])}" referrerpolicy="no-referrer"></div>' if imgs else ""
        facts = " · ".join((t.get("facts") or json.loads(t.get("facts_json") or "[]"))[:3])
        overview = f'<div class="gh"><span>{num}What it is</span><span>{_e(t.get("category"))}</span></div><h1>{_e(name)}</h1><p>{_e(desc or t.get("why_it_matters"))}</p>{shot}<p style="font-size:24px;color:#6A7085">{_e(facts)}</p>'
        setup = f'<div class="gh"><span>{num}How to set it up</span><span>{_e(name)}</span></div>'
        if r.get("install"):
            setup += '<h2><i>1</i>Install</h2><pre>' + _e("\n".join(r["install"])) + "</pre>"
        else:
            setup += f'<h2><i>1</i>Open it</h2><p>Go to the link below and follow the quick-start in the README.</p>'
        if r.get("features"):
            setup += '<h2><i>2</i>What you can do with it</h2><div class="fl">' + "".join(f"<div>{_e(f)}</div>" for f in r["features"][:5]) + "</div>"
        if len(imgs) > 1:
            setup += f'<div class="shot" style="max-height:380px"><img src="{_e(imgs[1])}" referrerpolicy="no-referrer" style="max-height:380px"></div>'
        setup += f'<div class="link">→ {_e(t.get("url"))}</div>'
        if total_tools > 3:  # keep packs short: overview + setup merged
            pages.append(overview.replace(shot, "") + setup.split("</div>", 1)[1])
        else:
            pages += [overview, setup]
    n = len(pages)
    return [f'<section class="g">{p}<div class="gh" style="margin-top:auto;padding-top:22px"><span>{_e(brand)} · {_e(handle)}</span><span>{k:02d}/{n:02d}</span></div></section>'
            for k, p in enumerate(pages, 1)]


def guide_document(items: List[Dict[str, Any]], brand: str, handle: str) -> (str, int):
    pages = guide_pages(items, brand, handle)
    doc = f'<!doctype html><html><head><meta charset="utf-8">{FONT_LINK}<style>{GUIDE_CSS}</style></head><body>{"".join(pages)}</body></html>'
    return doc, len(pages)


def dm_message(items: List[Dict[str, Any]]) -> str:
    """Copyable text sent with the guide images (Instagram text limit 1000 chars)."""
    out = ["Here's your guide 👇", ""]
    for i, it in enumerate(items, 1):
        t, r = it["topic"], it["readme"] or {}
        out.append(f"{i}. {display_title(t)}" if len(items) > 1 else display_title(t))
        for c in (r.get("install") or [])[:2 if len(items) > 1 else 4]:
            out.append(f"   {c}")
        out.append(f"   {t.get('url')}")
    out += ["", "Full step-by-step guide in the images above. Save this chat!"]
    text = "\n".join(out)
    return text if len(text) <= 1000 else text[:990] + "…"

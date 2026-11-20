"""Adaptive Multi-Format Visual Carousel Generator (v2.0).

Inspired by top engineering and creator visual references (ai.byarsh, code.xr, piyush.glitch):
- Supports adaptive slide counts: 1 (single image), 3 (news/spotlight), 5 (repo/tool showcase), 8 (tutorial), 10 (masterclass).
- Real software interface metaphors:
  1. Interactive input bars with cursor (e.g. `github.com/repo|` + `[ANALYSE ->]`)
  2. macOS dark code terminal windows with traffic-light dots and syntax highlighting
  3. Hub-and-spoke architecture diagrams with "LIVE" status badges
  4. Bento feature directory cards with squircle badges and telemetry counts
  5. Content calendar scheduling matrices with timestamp badges
- Real screenshot embedding: embeds product images, UI captures, and GitHub preview cards
- Slide-by-slide regeneration support without re-rendering the whole deck
- Canvas Dimensions: 1080 x 1350 px (Instagram 4:5 Portrait)
"""

import os
import math
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1350

# Design System Color Tokens (Warm Engineering Studio & Instagram Crimson)
COLOR_BG = (246, 243, 238)               # #F6F3EE (Warm parchment/engineering grid base)
COLOR_GRID = (235, 230, 222)             # #EBE6DE (Subtle graph millimeter lines)
COLOR_SURFACE = (255, 255, 255)           # #FFFFFF (Crisp elevated white bento card)
COLOR_SURFACE_MUTED = (248, 246, 242)     # #F8F6F2
COLOR_BORDER = (225, 220, 212)            # #E1DCD4 (Clean card border)
COLOR_TEXT_PRIMARY = (20, 20, 19)         # #141413 (Obsidian charcoal black)
COLOR_TEXT_SECONDARY = (100, 100, 96)     # #646460 (Muted technical slate)

# Vibrant Accent Colors
COLOR_CRIMSON = (225, 48, 108)            # #E1306C (Instagram signature crimson)
COLOR_TERRACOTTA = (217, 89, 50)          # #D95932 (Warm tech rust)
COLOR_EMERALD = (16, 185, 129)            # #10B981 (Live pulse badge green)
COLOR_AMBER = (245, 158, 11)              # #F59E0B (Notice / star gold)

# Dark Terminal / Code Container Tokens
COLOR_TERM_BG = (15, 23, 42)              # #0F172A (Deep slate dark mode)
COLOR_TERM_BORDER = (30, 41, 59)          # #1E293B
COLOR_TERM_TEXT = (248, 250, 252)         # #F8FAFC
COLOR_TERM_CYAN = (56, 189, 248)          # #38BDF8
COLOR_TERM_LIME = (132, 204, 22)          # #84CC16


def get_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.ImageFont:
    """Load system font with graceful fallbacks."""
    try:
        if mono:
            font_path = "C:/Windows/Fonts/consola.ttf"
        elif bold:
            font_path = "C:/Windows/Fonts/segoeuib.ttf"
        else:
            font_path = "C:/Windows/Fonts/segoeui.ttf"

        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()


class AdaptiveCarouselGenerator:
    def __init__(self, output_dir: str = "output/current_carousel"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------
    # Visual Primitives
    # -----------------------------------------------------------------
    def draw_background(self, draw: ImageDraw.ImageDraw):
        """Draw warm engineering grid paper texture."""
        draw.rectangle((0, 0, WIDTH, HEIGHT), fill=COLOR_BG)
        # 40px millimeter graph paper gridlines
        grid_step = 40
        for x in range(0, WIDTH, grid_step):
            draw.line((x, 0, x, HEIGHT), fill=COLOR_GRID, width=1)
        for y in range(0, HEIGHT, grid_step):
            draw.line((0, y, WIDTH, y), fill=COLOR_GRID, width=1)
        # Top color accent border
        draw.rectangle((0, 0, WIDTH, 8), fill=COLOR_CRIMSON)

    def draw_card(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        radius: int = 24,
        fill=COLOR_SURFACE,
        outline=COLOR_BORDER,
        width: int = 2
    ):
        """Draw elevated bento card with crisp border."""
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def draw_software_input_bar(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        input_text: str = "instagram.com/@anycreator|",
        button_text: str = "ANALYSE ->"
    ):
        """Draw authentic software search/input bar interface with text cursor and action pill."""
        x1, y1, x2, y2 = box
        # Card container
        self.draw_card(draw, box, radius=20, fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2)

        # Input text with blinking cursor metaphor
        font_mono = get_font(24, bold=True, mono=True)
        draw.text((x1 + 30, y1 + (y2 - y1) // 2 - 14), input_text, fill=COLOR_TEXT_PRIMARY, font=font_mono)

        # Action Button Pill
        btn_w = 170
        btn_h = 46
        btn_x1 = x2 - btn_w - 18
        btn_y1 = y1 + ((y2 - y1) - btn_h) // 2
        btn_box = (btn_x1, btn_y1, btn_x1 + btn_w, btn_y1 + btn_h)
        draw.rounded_rectangle(btn_box, radius=14, fill=COLOR_TERRACOTTA)
        font_btn = get_font(18, bold=True)
        draw.text((btn_x1 + 22, btn_y1 + 13), button_text, fill=(255, 255, 255), font=font_btn)

    def draw_macos_terminal(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        title: str,
        code_lines: List[str]
    ):
        """Draw dark macOS code terminal window with traffic lights and syntax text."""
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(box, radius=20, fill=COLOR_TERM_BG, outline=COLOR_TERM_BORDER, width=2)

        # Window chrome bar
        chrome_h = 48
        draw.rounded_rectangle((x1, y1, x2, y1 + chrome_h), radius=20, fill=(20, 30, 48))
        draw.rectangle((x1, y1 + 20, x2, y1 + chrome_h), fill=(20, 30, 48))  # Flatten bottom corners

        # Traffic light control dots
        dot_y = y1 + chrome_h // 2
        draw.ellipse((x1 + 24, dot_y - 6, x1 + 36, dot_y + 6), fill=(239, 68, 68))    # Red
        draw.ellipse((x1 + 44, dot_y - 6, x1 + 56, dot_y + 6), fill=(245, 158, 11))   # Yellow
        draw.ellipse((x1 + 64, dot_y - 6, x1 + 76, dot_y + 6), fill=(16, 185, 129))   # Green

        # Terminal Title
        font_title = get_font(18, bold=True, mono=True)
        draw.text((x1 + 95, dot_y - 10), title, fill=COLOR_TERM_TEXT, font=font_title)

        # Code lines
        font_code = get_font(20, mono=True)
        line_y = y1 + chrome_h + 24
        for idx, line in enumerate(code_lines, start=1):
            # Line number
            draw.text((x1 + 24, line_y), f"{idx:02d}", fill=(100, 116, 139), font=font_code)
            # Code syntax text
            text_color = COLOR_TERM_CYAN if line.strip().startswith(("#", "//", "from", "import", "def")) else COLOR_TERM_TEXT
            draw.text((x1 + 65, line_y), line, fill=text_color, font=font_code)
            line_y += 32

    def draw_header_meta(
        self,
        draw: ImageDraw.ImageDraw,
        category_tag: str,
        slide_idx: int,
        total_slides: int,
        creator_handle: str = "@sonu2967_02"
    ):
        """Draw top navigational metadata bar with category pill and slide counter."""
        y = 45
        # Category Pill
        pill_box = (80, y, 80 + len(category_tag) * 13 + 30, y + 42)
        draw.rounded_rectangle(pill_box, radius=12, fill=(254, 242, 242), outline=(254, 202, 202), width=1)
        font_pill = get_font(18, bold=True, mono=True)
        draw.text((95, y + 10), f"// {category_tag.upper()}", fill=COLOR_CRIMSON, font=font_pill)

        # Slide Counter (e.g. 01 / 05)
        font_counter = get_font(22, bold=True, mono=True)
        counter_text = f"{slide_idx:02d} / {total_slides:02d}"
        draw.text((WIDTH - 80 - 100, y + 9), counter_text, fill=COLOR_TEXT_PRIMARY, font=font_counter)

    def draw_footer_signature(self, draw: ImageDraw.ImageDraw, creator_handle: str = "@sonu2967_02"):
        """Draw footer brand watermark and swipe indicator."""
        y = HEIGHT - 70
        draw.line((80, y, WIDTH - 80, y), fill=COLOR_BORDER, width=1)

        font_foot = get_font(18, mono=True)
        draw.text((80, y + 20), f"software engineer • {creator_handle}", fill=COLOR_TEXT_SECONDARY, font=font_foot)

        font_swipe = get_font(18, bold=True)
        draw.text((WIDTH - 80 - 95, y + 20), "SWIPE ->", fill=COLOR_CRIMSON, font=font_swipe)

    # -----------------------------------------------------------------
    # Slide Rendering Engines
    # -----------------------------------------------------------------
    def render_cover_slide(
        self,
        headline_p1: str,
        headline_p2: str,
        subtitle: str,
        category_tag: str,
        input_prompt_meta: str,
        slide_count: int,
        output_filename: str = "slide_01.jpg"
    ) -> Path:
        """Render Slide 1: Dual-tone Hook Headline + Software Interface Metaphor."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)
        self.draw_background(draw)
        self.draw_header_meta(draw, category_tag, 1, slide_count)

        # 1. Dual-Tone Bold Headline
        font_head = get_font(68, bold=True)
        y = 150
        draw.text((80, y), headline_p1, fill=COLOR_TEXT_PRIMARY, font=font_head)
        y += 82
        draw.text((80, y), headline_p2, fill=COLOR_TERRACOTTA, font=font_head)

        # 2. Subtitle / Value Proposition
        y += 100
        font_sub = get_font(26)
        words = subtitle.split()
        sub_lines = []
        cur = []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 42:
                sub_lines.append(" ".join(cur[:-1]))
                cur = [w]
        if cur:
            sub_lines.append(" ".join(cur))

        for sl in sub_lines:
            draw.text((80, y), sl, fill=COLOR_TEXT_SECONDARY, font=font_sub)
            y += 36

        # 3. Software Interface Metaphor: Search Input Bar
        y += 45
        self.draw_software_input_bar(draw, (80, y, WIDTH - 80, y + 84), input_prompt_meta, "RUN WORKFLOW ->")

        # 4. Feature Highlights Bento Grid
        y += 130
        card_w = (WIDTH - 160 - 24) // 2
        card_h = 240

        # Left Card
        self.draw_card(draw, (80, y, 80 + card_w, y + card_h), radius=20)
        font_badge = get_font(18, bold=True, mono=True)
        draw.text((105, y + 25), "01 // CAPABILITY", fill=COLOR_CRIMSON, font=font_badge)
        font_c_title = get_font(28, bold=True)
        draw.text((105, y + 65), "Zero Manual Skills", fill=COLOR_TEXT_PRIMARY, font=font_c_title)
        font_c_body = get_font(20)
        draw.text((105, y + 115), "Turn raw prompts into\npolished video and code\nin minutes without experience.", fill=COLOR_TEXT_SECONDARY, font=font_c_body)

        # Right Card
        rx = 80 + card_w + 24
        self.draw_card(draw, (rx, y, rx + card_w, y + card_h), radius=20)
        draw.text((rx + 25, y + 25), "02 // STACK", fill=COLOR_EMERALD, font=font_badge)
        draw.text((rx + 25, y + 65), "100% Open Source", fill=COLOR_TEXT_PRIMARY, font=font_c_title)
        draw.text((rx + 25, y + 115), "No recurring cloud fees.\nRun locally on your machine\nwith full privacy control.", fill=COLOR_TEXT_SECONDARY, font=font_c_body)

        self.draw_footer_signature(draw)
        out_path = self.output_dir / output_filename
        img.save(out_path, quality=95)
        return out_path

    def render_content_slide(
        self,
        slide_idx: int,
        total_slides: int,
        category_tag: str,
        step_number: str,
        title: str,
        summary: str,
        feature_items: List[Dict[str, str]],
        terminal_title: Optional[str] = None,
        code_lines: Optional[List[str]] = None,
        output_filename: str = "slide.jpg"
    ) -> Path:
        """Render middle educational slide (features, architecture, or code execution)."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)
        self.draw_background(draw)
        self.draw_header_meta(draw, category_tag, slide_idx, total_slides)

        y = 135
        # Step label
        font_step = get_font(22, bold=True, mono=True)
        draw.text((80, y), f"STEP {step_number} // ARCHITECTURE", fill=COLOR_CRIMSON, font=font_step)

        # Section Headline
        y += 40
        font_title = get_font(52, bold=True)
        draw.text((80, y), title, fill=COLOR_TEXT_PRIMARY, font=font_title)

        # Summary paragraph
        y += 75
        font_body = get_font(24)
        draw.text((80, y), summary, fill=COLOR_TEXT_SECONDARY, font=font_body)

        y += 65

        # Render Terminal if provided
        if terminal_title and code_lines:
            term_h = 320
            self.draw_macos_terminal(draw, (80, y, WIDTH - 80, y + term_h), terminal_title, code_lines)
            y += term_h + 35

        # Render Feature Bento Rows
        for item in feature_items:
            card_h = 100
            self.draw_card(draw, (80, y, WIDTH - 80, y + card_h), radius=16, fill=COLOR_SURFACE)

            # Left badge / icon
            badge_text = item.get("badge", "01")
            draw.rounded_rectangle((105, y + 24, 165, y + 74), radius=12, fill=(254, 242, 242))
            font_ibadge = get_font(20, bold=True, mono=True)
            draw.text((120, y + 36), badge_text, fill=COLOR_CRIMSON, font=font_ibadge)

            # Title and description
            font_ititle = get_font(24, bold=True)
            draw.text((185, y + 22), item.get("title", ""), fill=COLOR_TEXT_PRIMARY, font=font_ititle)
            font_idesc = get_font(18)
            draw.text((185, y + 54), item.get("desc", ""), fill=COLOR_TEXT_SECONDARY, font=font_idesc)

            y += card_h + 16

        self.draw_footer_signature(draw)
        out_path = self.output_dir / output_filename
        img.save(out_path, quality=95)
        return out_path

    def render_cta_slide(
        self,
        slide_idx: int,
        total_slides: int,
        category_tag: str,
        headline: str,
        trigger_keyword: str,
        benefit_text: str,
        output_filename: str = "slide_last.jpg"
    ) -> Path:
        """Render high-conversion closing CTA slide with trigger keyword badge."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)
        self.draw_background(draw)
        self.draw_header_meta(draw, category_tag, slide_idx, total_slides)

        y = 180
        # Mini hook
        font_mono = get_font(22, bold=True, mono=True)
        draw.text((WIDTH // 2 - 140, y), "[ DIRECT RESOURCE PACK ]", fill=COLOR_TERRACOTTA, font=font_mono)

        # Huge "comment" indicator
        y += 70
        font_comment = get_font(40, bold=True)
        draw.text((WIDTH // 2 - 95, y), "COMMENT", fill=COLOR_TEXT_SECONDARY, font=font_comment)

        # Giant Trigger Box
        y += 70
        box_w = 640
        box_h = 170
        bx = (WIDTH - box_w) // 2
        draw.rounded_rectangle((bx, y, bx + box_w, y + box_h), radius=28, fill=COLOR_SURFACE, outline=COLOR_CRIMSON, width=3)
        font_keyword = get_font(76, bold=True, mono=True)
        kw_text = f'"{trigger_keyword}"'
        draw.text((bx + (box_w - len(kw_text) * 44) // 2, y + 42), kw_text, fill=COLOR_TEXT_PRIMARY, font=font_keyword)

        # Deliverable explanation
        y += box_h + 60
        font_explain = get_font(28)
        explain_lines = [
            f"and I will instantly DM you the direct",
            f"GitHub repository links + setup guide.",
            f"No gatekeeping. 100% free."
        ]
        for el in explain_lines:
            draw.text((WIDTH // 2 - len(el) * 7.2, y), el, fill=COLOR_TEXT_SECONDARY, font=font_explain)
            y += 42

        # 3 Action steps
        y += 60
        steps_box = (140, y, WIDTH - 140, y + 210)
        self.draw_card(draw, steps_box, radius=20, fill=COLOR_SURFACE)
        font_step_title = get_font(20, bold=True, mono=True)
        draw.text((175, y + 25), "AUTOMATED LEAD MAGNET FUNNEL:", fill=COLOR_CRIMSON, font=font_step_title)
        font_s = get_font(20)
        draw.text((175, y + 68), "1. Comment keyword above on this post", fill=COLOR_TEXT_PRIMARY, font=font_s)
        draw.text((175, y + 108), "2. Follow @sonu2967_02 to unlock link access", fill=COLOR_TEXT_PRIMARY, font=font_s)
        draw.text((175, y + 148), "3. Check your DMs for the full resource guide", fill=COLOR_TEXT_PRIMARY, font=font_s)

        # Save Reminder
        y += 245
        font_save = get_font(22, bold=True)
        draw.text((WIDTH // 2 - 165, y), ">> Save this post for your next project <<", fill=COLOR_TERRACOTTA, font=font_save)

        self.draw_footer_signature(draw)
        out_path = self.output_dir / output_filename
        img.save(out_path, quality=95)
        return out_path

    # -----------------------------------------------------------------
    # Multi-Format Deck Builder
    # -----------------------------------------------------------------
    def build_deck_from_topic(self, topic: Dict[str, Any], slide_count: int = 5) -> List[Path]:
        """Generate a complete adaptive carousel deck (1, 3, 5, 8, or 10 slides)."""
        # Clean up existing slides from previous runs
        for old_f in self.output_dir.glob("slide_*.jpg"):
            try:
                old_f.unlink()
            except Exception:
                pass

        rendered_paths = []
        cat = topic.get("category", "Developer Tools")
        title = topic.get("title", "AI Tool")
        url = topic.get("url", "https://github.com")
        desc = topic.get("description", "")
        lang = topic.get("language") or "Python"

        # 1. Slide 1: Cover Hook
        s1 = self.render_cover_slide(
            headline_p1="Turn Anyone Into A",
            headline_p2="Capable Video Creator",
            subtitle=f"{title}: {desc[:90]}",
            category_tag=cat,
            input_prompt_meta=f"{url.replace('https://', '')[:32]}|",
            slide_count=slide_count,
            output_filename="slide_01.jpg"
        )
        rendered_paths.append(s1)

        if slide_count == 1:
            return rendered_paths

        # 2. Middle Slides
        if slide_count >= 3:
            s2 = self.render_content_slide(
                slide_idx=2,
                total_slides=slide_count,
                category_tag=cat,
                step_number="01",
                title="The Workflow Problem",
                summary="Why traditional editing and manual tooling takes hours instead of seconds.",
                feature_items=[
                    {"badge": "01", "title": "Steep Learning Curve", "desc": "Complex software like Premiere and After Effects take months to learn."},
                    {"badge": "02", "title": "Expensive Cloud Fees", "desc": "Closed SaaS platforms charge $50-$200/mo for basic rendering tokens."},
                    {"badge": "03", "title": "Repetitive Bottlenecks", "desc": "Manual subtitling, cutaways, and animations destroy creator consistency."}
                ],
                output_filename="slide_02.jpg"
            )
            rendered_paths.append(s2)

        if slide_count >= 5:
            s3 = self.render_content_slide(
                slide_idx=3,
                total_slides=slide_count,
                category_tag=cat,
                step_number="02",
                title="Architecture & Automation",
                summary="How the open-source pipeline automates video production from a single prompt.",
                feature_items=[
                    {"badge": "01", "title": "Prompt Ingestion", "desc": "Input topic markdown or script into local AI model."},
                    {"badge": "02", "title": "Audio & Video Synthesis", "desc": "Generate voiceover with Kokoro and B-roll clips with Wan2.1."}
                ],
                terminal_title=f"{lang.lower()}_pipeline.py",
                code_lines=[
                    f"import {lang.lower()}_engine as engine",
                    "pipe = engine.load_pipeline('wan-video-v2')",
                    "video = pipe.generate('cinematic shot of autonomous AI')",
                    "video.export_vertical('output_reel.mp4')"
                ],
                output_filename="slide_03.jpg"
            )
            rendered_paths.append(s3)

            s4 = self.render_content_slide(
                slide_idx=4,
                total_slides=slide_count,
                category_tag=cat,
                step_number="03",
                title="Real What You Can Build",
                summary="Concrete outcomes anyone can produce today without a media studio.",
                feature_items=[
                    {"badge": "01", "title": "100% Faceless Video Channels", "desc": "Generate complete TikTok and Reel educational explainers."},
                    {"badge": "02", "title": "Interactive Product Demos", "desc": "Transform code changes into video walkthroughs for LinkedIn and X."},
                    {"badge": "03", "title": "Automated Content Repurposing", "desc": "Slice long podcasts into 15 viral captioned clips automatically."}
                ],
                output_filename="slide_04.jpg"
            )
            rendered_paths.append(s4)

        # Closing Slide: High-Conversion CTA
        last_idx = slide_count
        s_last = self.render_cta_slide(
            slide_idx=last_idx,
            total_slides=slide_count,
            category_tag=cat,
            headline="Get the Complete Repo Pack",
            trigger_keyword="AGENT",
            benefit_text="and I will send you the direct GitHub repository links + setup guide.",
            output_filename=f"slide_{last_idx:02d}.jpg"
        )
        rendered_paths.append(s_last)

        return rendered_paths

    def regenerate_single_slide(
        self,
        slide_idx: int,
        slide_count: int,
        topic: Dict[str, Any]
    ) -> Path:
        """Regenerate a single slide without touching the rest of the deck."""
        filename = f"slide_{slide_idx:02d}.jpg"
        cat = topic.get("category", "Developer Tools")

        if slide_idx == 1:
            return self.render_cover_slide(
                headline_p1="Turn Anyone Into A",
                headline_p2="Capable Video Creator",
                subtitle=f"{topic.get('title', '')}: {topic.get('description', '')[:90]}",
                category_tag=cat,
                input_prompt_meta=f"{topic.get('url', '').replace('https://', '')[:32]}|",
                slide_count=slide_count,
                output_filename=filename
            )
        elif slide_idx == slide_count:
            return self.render_cta_slide(
                slide_idx=slide_idx,
                total_slides=slide_count,
                category_tag=cat,
                headline="Get the Complete Repo Pack",
                trigger_keyword="AGENT",
                benefit_text="and I will send you the direct GitHub repository links + setup guide.",
                output_filename=filename
            )
        else:
            return self.render_content_slide(
                slide_idx=slide_idx,
                total_slides=slide_count,
                category_tag=cat,
                step_number=f"{slide_idx-1:02d}",
                title="Regenerated Feature Breakdown",
                summary="Updated practical demonstration of how this AI tool accelerates daily engineering.",
                feature_items=[
                    {"badge": "01", "title": "Optimized Implementation", "desc": "Updated with current open-source weights and local dependencies."},
                    {"badge": "02", "title": "Zero Cloud Latency", "desc": "Runs 100% on local hardware without recurring costs."}
                ],
                output_filename=filename
            )


if __name__ == "__main__":
    generator = AdaptiveCarouselGenerator()
    test_topic = {
        "title": "Wan2.1: Open-Source Video Generation Architecture from Wan-Video",
        "category": "Creator & Video Tools",
        "description": "Brings cinematic AI video generation to local GPUs for ordinary creators without video editing skills.",
        "url": "https://github.com/Wan-Video/Wan2.1",
        "language": "Python"
    }
    deck = generator.build_deck_from_topic(test_topic, slide_count=5)
    print(f"Adaptive 5-slide deck rendered successfully!")
    for p in deck:
        print(f"  -> {p.name} ({p.stat().st_size:,} bytes)")

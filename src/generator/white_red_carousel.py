"""Instagram-Native White & Red Carousel Generator.

Theme: Instagram Editorial White & Red
- Background: Soft Studio Off-White (#FAFAFA)
- Cards / Bento Surfaces: Pure Crisp White (#FFFFFF) with subtle 1px border (#E2E8F0)
- Brand Accent: Instagram Signature Red/Coral (#E1306C / #FD1D1D)
- Text Primary: Deep Rich Slate/Jet Black (#0F172A)
- Text Secondary: Cool Charcoal Slate (#64748B)
- Code / Execution Box: High-contrast Slate Dark Card (#0F172A) for crisp code readability
- Dimensions: 1080 x 1350 px (4:5 Portrait)
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1350

# White & Red Instagram Color Tokens
COLOR_BG = (250, 250, 252)             # #FAFAFC
COLOR_SURFACE = (255, 255, 255)         # #FFFFFF
COLOR_SURFACE_ALT = (248, 249, 250)     # #F8F9FA
COLOR_BORDER = (226, 232, 240)          # #E2E8F0
COLOR_TEXT_PRIMARY = (15, 23, 42)       # #0F172A (Deep Slate Black)
COLOR_TEXT_SECONDARY = (100, 116, 139)  # #64748B (Slate Gray)

# Instagram Red & Coral Accents
COLOR_INSTA_RED = (225, 48, 108)        # #E1306C (Instagram Crimson Pink/Red)
COLOR_INSTA_CORAL = (239, 68, 68)       # #EF4444 (Vibrant Red)
COLOR_INSTA_PILL_BG = (254, 242, 242)   # #FEF2F2 (Soft Red Pill Background)
COLOR_INSTA_PILL_BORDER = (254, 202, 202) # #FECACA

# Terminal / Code Container (Dark on White for high visual punch)
COLOR_TERMINAL_BG = (15, 23, 42)        # #0F172A
COLOR_TERMINAL_BORDER = (30, 41, 59)    # #1E293B
COLOR_TERMINAL_TEXT = (248, 250, 252)   # #F8FAFC
COLOR_TERMINAL_CYAN = (56, 189, 248)    # #38BDF8
COLOR_TERMINAL_MINT = (16, 185, 129)    # #10B981


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


class WhiteRedCarouselGenerator:
    def __init__(self, output_dir: str = "output/carousels"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def draw_card(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple,
        radius: int = 24,
        fill=COLOR_SURFACE,
        outline=COLOR_BORDER,
        width: int = 2,
    ):
        """Draw high-definition rounded container with optional border."""
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def render_cover_slide(
        self,
        headline: str,
        subtitle: str,
        accent_tag: str = "AI AUTOMATION STACK",
        creator_handle: str = "@sonu2967_02",
        slide_count: int = 10,
        output_filename: str = "slide_01.jpg",
    ) -> Path:
        """Render Slide 1: High-Contrast White & Red Instagram Cover Hook."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Subtle decorative gradient header bar at top
        draw.rectangle((0, 0, WIDTH, 8), fill=COLOR_INSTA_RED)

        # Ambient background pattern: soft concentric rings
        for r in range(480, 0, -40):
            alpha = int(4 * (1 - r / 480))
            box = (WIDTH // 2 - r, 460 - r, WIDTH // 2 + r, 460 + r)
            draw.ellipse(box, outline=(240 - alpha, 242 - alpha, 245 - alpha), width=3)

        # 1. Top Category Pill Tag (White & Red)
        font_mono = get_font(22, bold=True, mono=True)
        pill_text = f"// {accent_tag.upper()}"
        pill_w = len(pill_text) * 15 + 44
        pill_box = (WIDTH // 2 - pill_w // 2, 130, WIDTH // 2 + pill_w // 2, 185)
        self.draw_card(
            draw, pill_box, radius=26, fill=COLOR_INSTA_PILL_BG, outline=COLOR_INSTA_RED, width=2
        )
        draw.text(
            (WIDTH // 2, 158),
            pill_text,
            fill=COLOR_INSTA_RED,
            font=font_mono,
            anchor="mm",
        )

        # 2. Main Headline (Bold Rich Slate Black)
        font_headline = get_font(68, bold=True)
        words = headline.split()
        lines = []
        curr = []
        for w in words:
            curr.append(w)
            if len(" ".join(curr)) > 22:
                lines.append(" ".join(curr[:-1]))
                curr = [w]
        if curr:
            lines.append(" ".join(curr))

        y_offset = 245
        for line in lines:
            draw.text((WIDTH // 2, y_offset), line, fill=COLOR_TEXT_PRIMARY, font=font_headline, anchor="mm")
            y_offset += 86

        # Subtitle
        font_sub = get_font(30, bold=False)
        draw.text(
            (WIDTH // 2, y_offset + 10),
            subtitle,
            fill=COLOR_TEXT_SECONDARY,
            font=font_sub,
            anchor="mm",
        )

        # 3. Center Hero Mockup Card (Sleek Dark Terminal inside Light Canvas)
        card_box = (80, y_offset + 75, WIDTH - 80, HEIGHT - 180)
        self.draw_card(draw, card_box, radius=28, fill=COLOR_TERMINAL_BG, outline=COLOR_TERMINAL_BORDER, width=2)

        # Simulated macOS Title Bar
        dot_y = card_box[1] + 36
        draw.ellipse((card_box[0] + 32, dot_y - 8, card_box[0] + 48, dot_y + 8), fill=(239, 68, 68))
        draw.ellipse((card_box[0] + 58, dot_y - 8, card_box[0] + 74, dot_y + 8), fill=(245, 158, 11))
        draw.ellipse((card_box[0] + 84, dot_y - 8, card_box[0] + 100, dot_y + 8), fill=(16, 185, 129))

        draw.text(
            (WIDTH // 2, dot_y),
            "claude-workflow.terminal",
            fill=COLOR_TEXT_SECONDARY,
            font=get_font(20, mono=True),
            anchor="mm",
        )

        # Terminal Inner Logs
        inner_box = (card_box[0] + 32, card_box[1] + 70, card_box[2] - 32, card_box[3] - 36)
        self.draw_card(draw, inner_box, radius=18, fill=(10, 15, 28), outline=COLOR_TERMINAL_BORDER, width=1)

        p_font = get_font(24, mono=True)
        draw.text((inner_box[0] + 28, inner_box[1] + 35), "> anthropic.init_agent()", fill=COLOR_TERMINAL_CYAN, font=p_font)
        draw.text((inner_box[0] + 28, inner_box[1] + 80), "Loading 10 high-performance engineering repos...", fill=COLOR_TERMINAL_TEXT, font=p_font)
        draw.text((inner_box[0] + 28, inner_box[1] + 125), "[+] Verified with Claude 3.7 / 3.8", fill=COLOR_TERMINAL_MINT, font=p_font)
        draw.text((inner_box[0] + 28, inner_box[1] + 170), "[+] 100% Open-Source & Reproducible", fill=COLOR_TERMINAL_MINT, font=p_font)

        # 4. Bottom Footer (Author Handle & Red Swipe Cue)
        font_footer = get_font(22, mono=True)
        draw.text((80, HEIGHT - 80), creator_handle, fill=COLOR_TEXT_SECONDARY, font=font_footer)
        draw.text(
            (WIDTH - 80, HEIGHT - 80),
            f"SWIPE ->  01 / {slide_count:02d}",
            fill=COLOR_INSTA_RED,
            font=font_footer,
            anchor="ra",
        )

        out_path = self.output_dir / output_filename
        img.save(out_path, quality=95)
        return out_path

    def render_body_slide(
        self,
        slide_num: int,
        total_slides: int,
        badge_text: str,
        title: str,
        role_subtitle: str,
        points: List[str],
        code_or_metric: Optional[str] = None,
        creator_handle: str = "@sonu2967_02",
        output_filename: Optional[str] = None,
    ) -> Path:
        """Render Body Slide: Crisp White Bento with Red Badge & Dark Code Box."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Top Red Accent Stroke
        draw.rectangle((0, 0, WIDTH, 8), fill=COLOR_INSTA_RED)

        # 1. Header: Red Pill Badge
        font_mono = get_font(22, bold=True, mono=True)
        badge_w = len(badge_text) * 16 + 40
        badge_box = (80, 110, 80 + badge_w, 162)
        self.draw_card(
            draw, badge_box, radius=16, fill=COLOR_INSTA_PILL_BG, outline=COLOR_INSTA_RED, width=2
        )
        draw.text(
            (badge_box[0] + 20, 136),
            badge_text.upper(),
            fill=COLOR_INSTA_RED,
            font=font_mono,
            anchor="lm",
        )

        # 2. Title & Role Subtitle
        font_title = get_font(52, bold=True)
        draw.text((80, 205), title, fill=COLOR_TEXT_PRIMARY, font=font_title)

        font_role = get_font(30, bold=False)
        draw.text((80, 260), role_subtitle, fill=COLOR_INSTA_RED, font=font_role)

        # 3. Main Feature Box (Crisp White Card with fine border)
        feature_box = (80, 320, WIDTH - 80, 780)
        self.draw_card(draw, feature_box, radius=24, fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2)

        point_y = feature_box[1] + 45
        font_point = get_font(26, bold=False)
        for pt in points:
            # Red Accent Bullet
            draw.ellipse(
                (feature_box[0] + 35, point_y + 4, feature_box[0] + 47, point_y + 16),
                fill=COLOR_INSTA_RED,
            )
            draw.text(
                (feature_box[0] + 65, point_y),
                pt,
                fill=COLOR_TEXT_PRIMARY,
                font=font_point,
            )
            point_y += 65

        # 4. Code / Technical Snippet Box (High Contrast Dark Slate Card)
        if code_or_metric:
            code_box = (80, 815, WIDTH - 80, HEIGHT - 160)
            self.draw_card(draw, code_box, radius=20, fill=COLOR_TERMINAL_BG, outline=COLOR_TERMINAL_BORDER, width=2)

            # Code header tag
            draw.text(
                (code_box[0] + 30, code_box[1] + 30),
                "// PRACTICAL WORKFLOW / EXECUTION",
                fill=COLOR_TEXT_SECONDARY,
                font=get_font(20, mono=True),
            )

            font_code = get_font(23, mono=True)
            code_lines = code_or_metric.split("\n")
            c_y = code_box[1] + 75
            for cl in code_lines:
                draw.text((code_box[0] + 30, c_y), cl, fill=COLOR_TERMINAL_TEXT, font=font_code)
                c_y += 42

        # 5. Footer (Handle & Slide Numbers)
        font_footer = get_font(22, mono=True)
        draw.text((80, HEIGHT - 80), creator_handle, fill=COLOR_TEXT_SECONDARY, font=font_footer)
        draw.text(
            (WIDTH - 80, HEIGHT - 80),
            f"{slide_num:02d} / {total_slides:02d}",
            fill=COLOR_TEXT_SECONDARY,
            font=font_footer,
            anchor="ra",
        )

        filename = output_filename or f"slide_{slide_num:02d}.jpg"
        out_path = self.output_dir / filename
        img.save(out_path, quality=95)
        return out_path

    def render_cta_slide(
        self,
        cta_keyword: str,
        value_deliverable: str,
        creator_handle: str = "@sonu2967_02",
        slide_count: int = 10,
        output_filename: str = "slide_10.jpg",
    ) -> Path:
        """Render Slide 10: High-Converting White & Red Outro CTA."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Top Red Accent Stroke
        draw.rectangle((0, 0, WIDTH, 8), fill=COLOR_INSTA_RED)

        # Top Red Tag
        font_tag = get_font(26, bold=True, mono=True)
        draw.text(
            (WIDTH // 2, 220),
            "[ DIRECT RESOURCE PACK ]",
            fill=COLOR_INSTA_RED,
            font=font_tag,
            anchor="mm",
        )

        # Subtitle: COMMENT
        draw.text(
            (WIDTH // 2, 330),
            "COMMENT",
            fill=COLOR_TEXT_SECONDARY,
            font=get_font(34, bold=True, mono=True),
            anchor="mm",
        )

        # Huge Instagram-Red Keyword
        draw.text(
            (WIDTH // 2, 450),
            f'"{cta_keyword.upper()}"',
            fill=COLOR_INSTA_RED,
            font=get_font(88, bold=True),
            anchor="mm",
        )

        # Value Box (Crisp White Card with Soft Shadow)
        box = (100, 560, WIDTH - 100, 880)
        self.draw_card(draw, box, radius=24, fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2)

        font_deliv = get_font(32, bold=False)
        lines = []
        words = value_deliverable.split()
        curr = []
        for w in words:
            curr.append(w)
            if len(" ".join(curr)) > 26:
                lines.append(" ".join(curr[:-1]))
                curr = [w]
        if curr:
            lines.append(" ".join(curr))

        y = 650
        for l in lines:
            draw.text((WIDTH // 2, y), l, fill=COLOR_TEXT_PRIMARY, font=font_deliv, anchor="mm")
            y += 50

        # Save Reminder with Red Accent
        draw.text(
            (WIDTH // 2, 800),
            ">> Save this post for your next project <<",
            fill=COLOR_INSTA_RED,
            font=get_font(26, bold=True, mono=True),
            anchor="mm",
        )

        # Footer
        font_footer = get_font(22, mono=True)
        draw.text((80, HEIGHT - 80), creator_handle, fill=COLOR_TEXT_SECONDARY, font=font_footer)
        draw.text(
            (WIDTH - 80, HEIGHT - 80),
            f"{slide_count:02d} / {slide_count:02d}",
            fill=COLOR_TEXT_SECONDARY,
            font=font_footer,
            anchor="ra",
        )

        out_path = self.output_dir / output_filename
        img.save(out_path, quality=95)
        return out_path

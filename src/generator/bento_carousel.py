"""Minimalist Editorial Dark Bento Grid Carousel Generator.

Renders 1080x1350 px (4:5 portrait) high-resolution slides.
Follows the verified @trishaxbuilds & Bento Tech visual hierarchy:
- Deep obsidian backdrop (#0A0D14)
- Translucent frosted bento cards (#141A26)
- Monospace tags and high-contrast typography
- Safe zone margins (96px top/bottom, 72px left/right)
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

# Canvas dimensions
WIDTH = 1080
HEIGHT = 1350

# Color Tokens
COLOR_BG = (10, 13, 20)           # #0A0D14
COLOR_SURFACE = (20, 26, 38)       # #141A26
COLOR_SURFACE_ALT = (16, 21, 31)   # #10151F
COLOR_BORDER = (34, 45, 66)        # #222D42
COLOR_TEXT_PRIMARY = (248, 250, 252)  # #F8FAFC
COLOR_TEXT_SECONDARY = (148, 163, 184) # #94A3B8
COLOR_ACCENT_CYAN = (56, 189, 248)    # #38BDF8
COLOR_ACCENT_CORAL = (224, 122, 95)   # #E07A5F (Trisha terracotta)
COLOR_ACCENT_MINT = (16, 185, 129)    # #10B981
COLOR_ACCENT_AMBER = (245, 158, 11)   # #F59E0B


def get_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.ImageFont:
    """Load standard Windows fonts or fall back to PIL default."""
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


class BentoCarouselGenerator:
    def __init__(self, output_dir: str = "output/carousels"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def draw_rounded_card(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple,
        radius: int = 24,
        fill=COLOR_SURFACE,
        outline=COLOR_BORDER,
        width: int = 2,
    ):
        """Draw a high-definition rounded bento container."""
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def render_cover_slide(
        self,
        headline: str,
        subtitle: str,
        accent_tag: str = "CURATED AI STACK",
        creator_handle: str = "@software_engineer",
        slide_count: int = 10,
        output_filename: str = "slide_01.jpg",
    ) -> Path:
        """Render Slide 1: The High-Impact Cognitive Disruption Hook."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Subtle gradient / ambient glow in center
        for r in range(400, 0, -20):
            alpha = int(12 * (1 - r / 400))
            glow_box = (
                WIDTH // 2 - r,
                HEIGHT // 2 - r - 100,
                WIDTH // 2 + r,
                HEIGHT // 2 + r - 100,
            )
            # Soft radial glow emulation
            draw.ellipse(glow_box, outline=(20 + alpha, 28 + alpha, 45 + alpha), width=10)

        # 1. Top Category Pill Tag
        font_mono = get_font(24, bold=True, mono=True)
        pill_text = f"// {accent_tag.upper()}"
        pill_w = len(pill_text) * 16 + 40
        pill_box = (WIDTH // 2 - pill_w // 2, 130, WIDTH // 2 + pill_w // 2, 180)
        self.draw_rounded_card(
            draw, pill_box, radius=25, fill=COLOR_SURFACE_ALT, outline=COLOR_ACCENT_CORAL, width=2
        )
        draw.text(
            (WIDTH // 2, 155),
            pill_text,
            fill=COLOR_ACCENT_CORAL,
            font=font_mono,
            anchor="mm",
        )

        # 2. Main Hook Headline
        font_headline = get_font(68, bold=True)
        # Word wrap headline
        lines = []
        words = headline.split()
        curr_line = []
        for w in words:
            curr_line.append(w)
            if len(" ".join(curr_line)) > 22:
                lines.append(" ".join(curr_line[:-1]))
                curr_line = [w]
        if curr_line:
            lines.append(" ".join(curr_line))

        y_offset = 240
        for line in lines:
            draw.text((WIDTH // 2, y_offset), line, fill=COLOR_TEXT_PRIMARY, font=font_headline, anchor="mm")
            y_offset += 85

        # Subtitle
        font_sub = get_font(30, bold=False)
        draw.text(
            (WIDTH // 2, y_offset + 10),
            subtitle,
            fill=COLOR_TEXT_SECONDARY,
            font=font_sub,
            anchor="mm",
        )

        # 3. Center Hero Bento Window (Interactive Chat / Editor Mockup)
        card_box = (80, y_offset + 80, WIDTH - 80, HEIGHT - 180)
        self.draw_rounded_card(draw, card_box, radius=28, fill=COLOR_SURFACE, outline=COLOR_BORDER)

        # Simulated macOS Title Bar (traffic lights)
        dot_y = card_box[1] + 36
        draw.ellipse((card_box[0] + 32, dot_y - 8, card_box[0] + 48, dot_y + 8), fill=(239, 68, 68))
        draw.ellipse((card_box[0] + 58, dot_y - 8, card_box[0] + 74, dot_y + 8), fill=(245, 158, 11))
        draw.ellipse((card_box[0] + 84, dot_y - 8, card_box[0] + 100, dot_y + 8), fill=(16, 185, 129))

        # Title bar label
        draw.text(
            (WIDTH // 2, dot_y),
            "claude-workflow.terminal",
            fill=COLOR_TEXT_SECONDARY,
            font=get_font(20, mono=True),
            anchor="mm",
        )

        # Simulated Terminal / Prompt Block
        inner_box = (card_box[0] + 36, card_box[1] + 70, card_box[2] - 36, card_box[3] - 40)
        self.draw_rounded_card(draw, inner_box, radius=18, fill=COLOR_SURFACE_ALT, outline=COLOR_BORDER)

        prompt_font = get_font(24, mono=True)
        draw.text(
            (inner_box[0] + 28, inner_box[1] + 35),
            "> anthropic.init_agent()",
            fill=COLOR_ACCENT_CYAN,
            font=prompt_font,
        )
        draw.text(
            (inner_box[0] + 28, inner_box[1] + 80),
            "Loading 10 high-performance engineering repos...",
            fill=COLOR_TEXT_PRIMARY,
            font=prompt_font,
        )
        draw.text(
            (inner_box[0] + 28, inner_box[1] + 125),
            "[+] Verified with Claude 3.7 / 3.8",
            fill=COLOR_ACCENT_MINT,
            font=prompt_font,
        )
        draw.text(
            (inner_box[0] + 28, inner_box[1] + 170),
            "[+] 100% Open-Source & Reproducible",
            fill=COLOR_ACCENT_MINT,
            font=prompt_font,
        )

        # 4. Bottom Footer (Author Handle & Swipe Indicator)
        font_footer = get_font(22, mono=True)
        draw.text((80, HEIGHT - 80), creator_handle, fill=COLOR_TEXT_SECONDARY, font=font_footer)
        draw.text(
            (WIDTH - 80, HEIGHT - 80),
            f"SWIPE ->  01 / {slide_count:02d}",
            fill=COLOR_ACCENT_CORAL,
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
        creator_handle: str = "@software_engineer",
        output_filename: Optional[str] = None,
    ) -> Path:
        """Render a body value slide (Tool / Repo / Step / Analysis)."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # 1. Header: Badge Tag
        font_mono = get_font(22, bold=True, mono=True)
        badge_box = (80, 110, 80 + len(badge_text) * 16 + 36, 160)
        self.draw_rounded_card(
            draw, badge_box, radius=14, fill=COLOR_SURFACE_ALT, outline=COLOR_ACCENT_CORAL, width=2
        )
        draw.text(
            (badge_box[0] + 18, 135),
            badge_text.upper(),
            fill=COLOR_ACCENT_CORAL,
            font=font_mono,
            anchor="lm",
        )

        # 2. Title & Role Subtitle
        font_title = get_font(52, bold=True)
        draw.text((80, 205), title, fill=COLOR_TEXT_PRIMARY, font=font_title)

        font_role = get_font(30, bold=False)
        draw.text((80, 260), role_subtitle, fill=COLOR_ACCENT_CYAN, font=font_role)

        # 3. Main Bento Feature Box (UI / Diagram / Card showcase)
        feature_box = (80, 320, WIDTH - 80, 780)
        self.draw_rounded_card(draw, feature_box, radius=24, fill=COLOR_SURFACE, outline=COLOR_BORDER)

        # Points inside the feature box
        point_y = feature_box[1] + 45
        font_point = get_font(26, bold=False)
        for pt in points:
            # Bullet icon
            draw.ellipse(
                (feature_box[0] + 35, point_y + 4, feature_box[0] + 47, point_y + 16),
                fill=COLOR_ACCENT_CYAN,
            )
            draw.text(
                (feature_box[0] + 65, point_y),
                pt,
                fill=COLOR_TEXT_PRIMARY,
                font=font_point,
            )
            point_y += 65

        # 4. Code / Technical Snippet Box (Bottom Bento Card)
        if code_or_metric:
            code_box = (80, 815, WIDTH - 80, HEIGHT - 160)
            self.draw_rounded_card(draw, code_box, radius=20, fill=COLOR_SURFACE_ALT, outline=COLOR_BORDER)

            # Code tag
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
                draw.text((code_box[0] + 30, c_y), cl, fill=COLOR_TEXT_PRIMARY, font=font_code)
                c_y += 42

        # 5. Footer (Creator Signature & Pagination)
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
        creator_handle: str = "@software_engineer",
        slide_count: int = 10,
        output_filename: str = "slide_10.jpg",
    ) -> Path:
        """Render the High-Converting Outro CTA Slide."""
        img = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Top Accent Tag
        font_tag = get_font(26, bold=True, mono=True)
        draw.text(
            (WIDTH // 2, 220),
            "[ DIRECT RESOURCE PACK ]",
            fill=COLOR_ACCENT_CORAL,
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

        # The Huge Serif Keyword
        draw.text(
            (WIDTH // 2, 450),
            f'"{cta_keyword.upper()}"',
            fill=COLOR_TEXT_PRIMARY,
            font=get_font(88, bold=True),
            anchor="mm",
        )

        # Value Box
        box = (100, 560, WIDTH - 100, 880)
        self.draw_rounded_card(draw, box, radius=24, fill=COLOR_SURFACE, outline=COLOR_BORDER)

        font_deliv = get_font(32, bold=False)
        lines = []
        words = value_deliverable.split()
        curr_line = []
        for w in words:
            curr_line.append(w)
            if len(" ".join(curr_line)) > 26:
                lines.append(" ".join(curr_line[:-1]))
                curr_line = [w]
        if curr_line:
            lines.append(" ".join(curr_line))

        y = 650
        for l in lines:
            draw.text((WIDTH // 2, y), l, fill=COLOR_TEXT_PRIMARY, font=font_deliv, anchor="mm")
            y += 50

        # Micro-copy bookmark prompt
        draw.text(
            (WIDTH // 2, 800),
            ">> Save this post for your next project <<",
            fill=COLOR_ACCENT_AMBER,
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

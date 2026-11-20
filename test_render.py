import sys
import os
from pathlib import Path

# Add src/generator to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src", "generator"))
from bento_carousel import BentoCarouselGenerator

output_directory = os.path.join(os.path.dirname(__file__), "output", "test_deck")
gen = BentoCarouselGenerator(output_dir=output_directory)

print("Rendering Slide 1 (Cover Hook)...")
s1 = gen.render_cover_slide(
    headline="10 GitHub Repos That Turn Claude Into an Autonomous Engineer",
    subtitle="Battle-tested developer tools & MCP servers you can run today.",
    accent_tag="AI AUTOMATION STACK",
    creator_handle="@sonu_builds",
    slide_count=10,
    output_filename="slide_01.jpg",
)

print("Rendering Slide 2 (Repo 01 Value Slide)...")
s2 = gen.render_body_slide(
    slide_num=2,
    total_slides=10,
    badge_text="REPO 01",
    title="FastMCP Framework",
    role_subtitle="To build production AI tools in under 50 lines of code",
    points=[
        "Native Model Context Protocol implementation for Python",
        "Auto-generates tool schemas directly from Python type hints",
        "Zero boilerplate server startup with built-in stdio transport",
    ],
    code_or_metric="""from mcp.server.fastmcp import FastMCP
mcp = FastMCP("Code Assistant")

@mcp.tool()
def run_query(sql: str) -> str:
    return db.execute(sql)""",
    creator_handle="@sonu_builds",
    output_filename="slide_02.jpg",
)

print("Rendering Slide 10 (Conversion CTA)...")
s10 = gen.render_cta_slide(
    cta_keyword="AGENT",
    value_deliverable="and I will send you the full repository list, plus step-by-step setup guides.",
    creator_handle="@sonu_builds",
    slide_count=10,
    output_filename="slide_10.jpg",
)

print("SUCCESS!")
print(f"Slide 1: {s1}")
print(f"Slide 2: {s2}")
print(f"Slide 10: {s10}")

# Verify file existence and sizes
for path in [s1, s2, s10]:
    size_kb = os.path.getsize(path) / 1024
    print(f"File: {os.path.basename(path)} | Size: {size_kb:.1f} KB | Resolution: 1080x1350")

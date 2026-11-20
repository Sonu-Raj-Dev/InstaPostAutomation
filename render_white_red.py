import sys
import os
from pathlib import Path

# Add src/generator to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src", "generator"))
from white_red_carousel import WhiteRedCarouselGenerator

# Render into current_carousel so the dashboard immediately shows the new White & Red deck!
output_directory = os.path.join(os.path.dirname(__file__), "output", "current_carousel")
gen = WhiteRedCarouselGenerator(output_dir=output_directory)

headline = "10 GitHub Repos That Turn Claude Into an Autonomous Engineer"
subtitle = "Battle-tested developer tools & MCP servers you can run today."
cta_keyword = "AGENT"

print("Rendering Slide 1 (White & Red Cover Hook)...")
s1 = gen.render_cover_slide(
    headline=headline,
    subtitle=subtitle,
    accent_tag="AI AUTOMATION STACK",
    creator_handle="@sonu2967_02",
    slide_count=10,
    output_filename="slide_01.jpg",
)

slides_data = [
    {
        "badge": "REPO 01",
        "title": "FastMCP Framework",
        "role": "To build production AI tools in under 50 lines of code",
        "points": [
            "Native Model Context Protocol implementation for Python",
            "Auto-generates tool schemas directly from Python type hints",
            "Zero boilerplate server startup with built-in stdio transport",
        ],
        "code": "from mcp.server.fastmcp import FastMCP\nmcp = FastMCP('Code Assistant')\n\n@mcp.tool()\ndef run_query(sql: str) -> str:\n    return db.execute(sql)",
    },
    {
        "badge": "REPO 02",
        "title": "Claude Agent SDK",
        "role": "To orchestrate autonomous multi-agent dev teams",
        "points": [
            "Isolated workspace branching per subagent",
            "Deterministic tool call execution and event logging",
            "Reactive messaging without busy-polling loops",
        ],
        "code": "from claude_agent import Agent\nworker = Agent(role='Security Auditor')\nresult = worker.run('Audit auth routes')",
    },
    {
        "badge": "REPO 03",
        "title": "vLLM High-Throughput Engine",
        "role": "To serve open-source LLMs with 24x higher throughput",
        "points": [
            "PagedAttention algorithm eliminates memory fragmentation",
            "Continuous batching of incoming inference requests",
            "Full compatibility with OpenAI API client format",
        ],
        "code": "vllm serve deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \\\n  --port 8000 --gpu-memory-utilization 0.95",
    },
    {
        "badge": "REPO 04",
        "title": "Whisper.cpp",
        "role": "To transcribe audio locally with zero GPU requirements",
        "points": [
            "High-performance C/C++ port of OpenAI Whisper",
            "Zero external dependencies, pure local execution",
            "Optimized for Apple Silicon and modern x86 AVX2",
        ],
        "code": "./main -m models/ggml-base.en.bin -f podcast.wav -osrt",
    },
    {
        "badge": "REPO 05",
        "title": "yt-dlp Engine",
        "role": "To ingest raw video and audio feeds into AI pipelines",
        "points": [
            "Extract audio streams directly into Whisper pipelines",
            "Supports format filtering and metadata extraction",
            "Essential utility for multi-modal dataset building",
        ],
        "code": "yt-dlp -x --audio-format wav -o '%(id)s.%(ext)s' <URL>",
    },
    {
        "badge": "REPO 06",
        "title": "SQLite-Vec",
        "role": "To run vector search directly inside embedded SQLite",
        "points": [
            "Zero infrastructure vector database for local AI apps",
            "SIMD-accelerated cosine distance and L2 distance",
            "Runs anywhere SQLite runs with zero client-server latency",
        ],
        "code": "SELECT rowid, distance FROM vec_articles\nWHERE embedding MATCH ? ORDER BY distance LIMIT 5;",
    },
    {
        "badge": "REPO 07",
        "title": "HyperFrames",
        "role": "To generate programmatic motion graphics from code",
        "points": [
            "Render frame-accurate video from HTML, CSS, and WebGL",
            "Generates explainers, tech demos, and animated tutorials",
            "Full Node.js and Chromium headless pipeline support",
        ],
        "code": "<Sequence from={0} duration={60}>\n  <AnimatedChart data={benchmarks} />\n</Sequence>",
    },
    {
        "badge": "REPO 08",
        "title": "Awesome MCP Servers",
        "role": "To discover over 500+ community integrations",
        "points": [
            "Curated directory of databases, developer tools, and APIs",
            "Categorized by official, enterprise, and community tiers",
            "Essential index for building agentic tool workflows",
        ],
        "code": "# Explore categories: DBs, Cloud, DevTools, Search",
    },
]

for idx, slide in enumerate(slides_data, start=2):
    print(f"Rendering Slide {idx} ({slide['title']})...")
    gen.render_body_slide(
        slide_num=idx,
        total_slides=10,
        badge_text=slide["badge"],
        title=slide["title"],
        role_subtitle=slide["role"],
        points=slide["points"],
        code_or_metric=slide.get("code"),
        creator_handle="@sonu2967_02",
        output_filename=f"slide_{idx:02d}.jpg",
    )

print("Rendering Slide 10 (White & Red CTA)...")
s10 = gen.render_cta_slide(
    cta_keyword=cta_keyword,
    value_deliverable="and I will send you the direct GitHub repository links + setup guide.",
    creator_handle="@sonu2967_02",
    slide_count=10,
    output_filename="slide_10.jpg",
)

print("SUCCESS: Rendered all 10 White & Red slides into output/current_carousel!")

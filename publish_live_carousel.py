"""Standalone 10-Slide White & Red Carousel Publisher.

Publishes all 10 slides from output/current_carousel to @sonu2967_02 via Meta Graph API.
"""

import os
import sys
from pathlib import Path
import requests
from dotenv import load_dotenv

CMS_ROOT = Path(__file__).parent
sys.path.append(str(CMS_ROOT / "src"))

from meta_graph_client import MetaGraphClient
from utils.media_uploader import upload_to_public_host

load_dotenv()

client = MetaGraphClient()

slides_dir = CMS_ROOT / "output" / "current_carousel"
slide_files = sorted([slides_dir / f"slide_{i:02d}.jpg" for i in range(1, 11)])

print("==================================================")
print("10-SLIDE WHITE & RED CAROUSEL PUBLISHER")
print(f"Target Account: {client.ig_user_id} (@sonu2967_02)")
print("==================================================")

# 1. Verify all 10 slide files exist
for sf in slide_files:
    if not sf.exists():
        print(f"Error: Missing {sf.name}")
        sys.exit(1)
print(f"Verified all 10 slide files in {slides_dir}")

# 2. Upload slides to public HTTPS endpoints
print("\nStep 1: Staging 10 slides onto public HTTPS endpoints for Meta servers...")
image_urls = []
for idx, sf in enumerate(slide_files, start=1):
    print(f"  Uploading slide {idx:02d}/10 ({sf.name})...")
    url = upload_to_public_host(str(sf))
    if not url:
        print(f"Failed uploading {sf.name}!")
        sys.exit(1)
    print(f"  -> {url}")
    image_urls.append(url)

# 3. Formulate Caption
caption = """10 GitHub Repos That Turn Claude Into an Autonomous Engineer 🚀

Battle-tested developer tools and MCP servers you can run today:

1. FastMCP: Production MCP tools in Python
2. Claude Agent SDK: Subagent orchestration
3. vLLM: High-throughput local LLM serving
4. Whisper.cpp: Local speech transcription
5. yt-dlp: Multi-modal media ingest
6. SQLite-Vec: Embedded vector search
7. HyperFrames: Programmatic motion graphics
8. Awesome MCP: 500+ community tools

Which tool are you adding to your developer stack first?👇

>> Save this post for your next project <<

#SoftwareEngineering #AITools #ClaudeAI #Python #DeveloperTools #OpenSource #MachineLearning #DevOps"""

# 4. Trigger Meta Carousel Publishing
print("\nStep 2: Executing Meta Graph API 4-step Carousel Publishing...")
res = client.publish_carousel(image_urls=image_urls, caption=caption)

if res.get("success"):
    post_id = res["post_id"]
    print("\n==================================================")
    print(f"CAROUSEL SUCCESSFULLY PUBLISHED!")
    print(f"Post ID: {post_id}")

    # Fetch permalink
    perm_url = f"https://graph.facebook.com/v22.0/{post_id}?fields=permalink&access_token={client.access_token}"
    perm_resp = requests.get(perm_url)
    if perm_resp.status_code == 200:
        permalink = perm_resp.json().get("permalink")
        print(f"LIVE POST LINK: {permalink}")
    print("==================================================")
else:
    print(f"\nPublishing failed: {res}")

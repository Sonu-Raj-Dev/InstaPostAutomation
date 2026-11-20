"""Instagram Controller MCP (Model Context Protocol) Server.

Supports:
1. Official Direct Meta Instagram Graph API (Primary, 100% Free)
2. Metricool API Controller (Secondary / Alternative)

Exposes native tools to AI agents for:
- Testing credentials and connectivity
- Exchanging Short-Lived Tokens for 60-Day Long-Lived Tokens
- Discovering linked Instagram Business / Creator accounts
- Publishing multi-image carousels and single posts
- Fetching real-time Insights (reach, impressions, saves, shares)
"""

import os
import json
import logging
from typing import List, Optional
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

import sys
sys.path.append(os.path.dirname(__file__))
from meta_graph_client import MetaGraphClient
from metricool_client import MetricoolClient

load_dotenv()
logger = logging.getLogger("InstagramMCPServer")

# Initialize FastMCP Server
mcp = FastMCP("Instagram Graph API & CMS Controller")
meta_client = MetaGraphClient()
metricool_client = MetricoolClient()


# ==========================================
# META GRAPH API TOOLS (OFFICIAL / DIRECT)
# ==========================================

@mcp.tool()
def meta_discover_instagram_account() -> str:
    """Discover the linked Instagram Professional Account ID and username from your Meta token."""
    res = meta_client.discover_instagram_account_id()
    return json.dumps(res, indent=2)


@mcp.tool()
def meta_exchange_token(short_lived_token: str) -> str:
    """Exchange a short-lived token from Graph API Explorer for a 60-day auto-refreshing Long-Lived Token.

    Requires META_APP_ID and META_APP_SECRET in .env.
    """
    res = meta_client.exchange_for_long_lived_token(short_lived_token)
    return json.dumps(res, indent=2)


@mcp.tool()
def meta_publish_carousel(image_urls: List[str], caption: str) -> str:
    """Publish a multi-image carousel (2-10 slides) directly to Instagram via Meta Graph API.

    Args:
        image_urls: List of publicly accessible HTTPS URLs (1080x1350 JPEG).
        caption: Formatted post caption including hook, value, and CTA.

    Returns:
        JSON response with the published live post ID.
    """
    res = meta_client.publish_carousel(image_urls=image_urls, caption=caption)
    return json.dumps(res, indent=2)


@mcp.tool()
def meta_get_account_insights() -> str:
    """Fetch daily account reach, impressions, and profile views directly from Meta."""
    res = meta_client.get_account_insights()
    return json.dumps(res, indent=2)


@mcp.tool()
def meta_get_post_insights(post_id: str) -> str:
    """Fetch saves, shares, reach, and interactions for a specific published post ID."""
    res = meta_client.get_media_insights(post_id)
    return json.dumps(res, indent=2)


# ==========================================
# METRICOOL TOOLS (ALTERNATIVE / COMPLEMENTARY)
# ==========================================

@mcp.tool()
def metricool_test_connection() -> str:
    """Test connection to the Metricool Instagram workspace (blogId: 7911973, userId: 6200964)."""
    res = metricool_client.test_connection()
    return json.dumps(res, indent=2)


@mcp.tool()
def metricool_schedule_carousel(
    caption: str,
    publication_datetime: str,
    image_urls: List[str],
    timezone: str = "Asia/Kolkata",
) -> str:
    """Schedule a multi-image carousel post to Instagram via Metricool Calendar."""
    res = metricool_client.schedule_post(
        text=caption,
        publication_date=publication_datetime,
        media_urls=image_urls,
        network="instagram",
        auto_publish=True,
        timezone_str=timezone,
    )
    return json.dumps(res, indent=2)


if __name__ == "__main__":
    mcp.run()

"""Metricool API Client for Instagram Content Publishing & Analytics.

Workspace:
  userId: 6200964
  blogId: 7911973
  Instagram Evolution: https://app.metricool.com/evolution/instagram?blogId=7911973&userId=6200964
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MetricoolClient")

BASE_URL = "https://app.metricool.com/api"


class MetricoolClient:
    def __init__(
        self,
        user_token: Optional[str] = None,
        user_id: Optional[str] = None,
        blog_id: Optional[str] = None,
    ):
        self.user_token = user_token or os.getenv("METRICOOL_TOKEN", "").strip()
        self.user_id = user_id or os.getenv("METRICOOL_USER_ID", "6200964").strip()
        self.blog_id = blog_id or os.getenv("METRICOOL_BLOG_ID", "7911973").strip()

        if not self.user_token:
            logger.warning(
                "Metricool userToken is missing. Set METRICOOL_TOKEN in your .env file."
            )

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "X-Mc-Auth": self.user_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def test_connection(self) -> Dict[str, Any]:
        """Test API connectivity and retrieve account status."""
        if not self.user_token:
            return {
                "success": False,
                "error": "METRICOOL_TOKEN is not configured. Add it to .env.",
            }

        url = f"{BASE_URL}/stats/timeline/igFollowers"
        params = {
            "userId": self.user_id,
            "blogId": self.blog_id,
            "start": datetime.now().strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 200:
                return {
                    "success": True,
                    "status_code": 200,
                    "userId": self.user_id,
                    "blogId": self.blog_id,
                    "data": resp.json(),
                }
            elif resp.status_code in (401, 403):
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": "Authentication failed. Check your Metricool userToken in Account Settings -> API.",
                }
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "response": resp.text,
                }
        except Exception as e:
            logger.error(f"Error testing Metricool connection: {e}")
            return {"success": False, "error": str(e)}

    def normalize_media_url(self, media_url: str) -> Optional[str]:
        """Send an image URL to Metricool to download, normalize and host on their CDN."""
        url = f"{BASE_URL}/actions/normalize/image/url"
        params = {"url": media_url}
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("url") or data.get("mediaId")
            else:
                logger.error(f"Normalize failed ({resp.status_code}): {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Exception normalizing media URL {media_url}: {e}")
            return None

    def schedule_post(
        self,
        text: str,
        publication_date: str,
        media_urls: Optional[List[str]] = None,
        network: str = "instagram",
        auto_publish: bool = True,
        timezone_str: str = "Asia/Kolkata",
    ) -> Dict[str, Any]:
        """Schedule a post or carousel for Instagram via Metricool Scheduler.

        Parameters:
            text: Caption copy, formatting, and hashtag list.
            publication_date: ISO 8601 string, e.g. "2026-11-21T19:00:00".
            media_urls: List of image URLs (1 for single post, 2-10 for carousel).
            network: Target network ("instagram").
            auto_publish: True to automatically post without mobile confirmation.
            timezone_str: Timezone for the scheduled release (default: Asia/Kolkata).
        """
        endpoint = f"{BASE_URL}/v2/scheduler/posts"
        params = {"userId": self.user_id, "blogId": self.blog_id}

        # Build media list
        formatted_media = []
        if media_urls:
            for url in media_urls:
                formatted_media.append({"url": url, "type": "IMAGE"})

        payload = {
            "text": text,
            "publicationDate": {
                "dateTime": publication_date,
                "timezone": timezone_str,
            },
            "networks": [network.lower()],
            "autoPublish": auto_publish,
            "media": formatted_media,
        }

        try:
            resp = requests.post(
                endpoint, headers=self.headers, params=params, json=payload, timeout=20
            )
            if resp.status_code in (200, 201):
                logger.info("Post scheduled successfully on Metricool!")
                return {"success": True, "data": resp.json()}
            else:
                logger.error(f"Failed to schedule post ({resp.status_code}): {resp.text}")
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": resp.text,
                }
        except Exception as e:
            logger.error(f"Exception scheduling post: {e}")
            return {"success": False, "error": str(e)}

    def get_instagram_followers(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """Fetch daily Instagram follower metrics between start_date and end_date (YYYY-MM-DD)."""
        url = f"{BASE_URL}/stats/timeline/igFollowers"
        params = {
            "userId": self.user_id,
            "blogId": self.blog_id,
            "start": start_date,
            "end": end_date,
        }
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=15)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_reels_analytics(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """Fetch Reels metrics and reach."""
        url = f"{BASE_URL}/v2/analytics/reels/instagram"
        params = {
            "userId": self.user_id,
            "blogId": self.blog_id,
            "from": from_date,
            "to": to_date,
        }
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=15)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_post_comments(self) -> Dict[str, Any]:
        """Retrieve recent post comments and engagement."""
        url = f"{BASE_URL}/v2/inbox/post-comments"
        params = {"userId": self.user_id, "blogId": self.blog_id}
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=15)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

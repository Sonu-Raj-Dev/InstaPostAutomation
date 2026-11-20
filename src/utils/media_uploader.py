"""Media Uploader Utility.

Stages local 1080x1350 JPEG slides onto public HTTPS endpoints
so Meta Graph API servers can download and ingest them during container creation.
"""

import os
import requests
from dotenv import load_dotenv
from typing import Optional

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass


def upload_to_public_host(file_path: str) -> Optional[str]:
    """Upload a local image file to a public HTTPS host (Freeimage/iili.io primary, Catbox fallback)."""
    if not os.path.exists(file_path):
        return None

    load_dotenv()
    # Primary: freeimage.host (key in .env as FREEIMAGE_API_KEY) (fast CDN, Meta-compatible iili.io links)
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://freeimage.host/api/1/upload",
                data={
                    "key": os.getenv("FREEIMAGE_API_KEY", ""),
                    "action": "upload",
                    "format": "json"
                },
                files={"source": f},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                img_url = data.get("image", {}).get("url")
                if img_url:
                    return img_url
    except Exception as e:
        print(f"Freeimage host upload error for {file_path}: {e}")

    # Fallback: Catbox
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                timeout=25,
            )
            if resp.status_code == 200 and resp.text.startswith("http"):
                return resp.text.strip()
    except Exception as e:
        print(f"Catbox upload error for {file_path}: {e}")

    return None

import os
import time
import requests
from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "17841432923011052").strip()

IMAGE_URL = "https://files.catbox.moe/smootb.jpg"
CAPTION = """10 GitHub Repos That Turn Claude Into an Autonomous Engineer 🚀

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

print("==================================================")
print(f"Target Instagram Account ID: {IG_USER_ID}")
print(f"Image URL: {IMAGE_URL}")
print("==================================================")

# Step 1: Create Media Container
print("Step 1: Creating Meta Media Container...")
container_url = f"https://graph.facebook.com/v22.0/{IG_USER_ID}/media"
payload = {
    "image_url": IMAGE_URL,
    "caption": CAPTION,
    "access_token": ACCESS_TOKEN,
}

resp = requests.post(container_url, data=payload, timeout=20)
print("Create container response:", resp.status_code, resp.json())

if resp.status_code != 200 or "id" not in resp.json():
    print("FAILED creating container!")
    exit(1)

container_id = resp.json()["id"]
print(f"Container created successfully. ID: {container_id}")

# Step 2: Poll Container Status until FINISHED
print("Step 2: Checking container status...")
status_url = f"https://graph.facebook.com/v22.0/{container_id}"
params = {"fields": "status_code", "access_token": ACCESS_TOKEN}

for attempt in range(15):
    status_resp = requests.get(status_url, params=params, timeout=10)
    if status_resp.status_code == 200:
        status_data = status_resp.json()
        status_code = status_data.get("status_code", "IN_PROGRESS")
        print(f"Attempt {attempt+1}: Status = {status_code}")
        if status_code == "FINISHED":
            break
        elif status_code == "ERROR":
            print("Container processing failed with ERROR:", status_data)
            exit(1)
    time.sleep(2)

# Step 3: Publish the Container
print("Step 3: Publishing media container...")
publish_url = f"https://graph.facebook.com/v22.0/{IG_USER_ID}/media_publish"
publish_payload = {
    "creation_id": container_id,
    "access_token": ACCESS_TOKEN,
}

pub_resp = requests.post(publish_url, data=publish_payload, timeout=20)
print("Publish response:", pub_resp.status_code, pub_resp.json())

if pub_resp.status_code != 200 or "id" not in pub_resp.json():
    print("FAILED publishing container!")
    exit(1)

post_id = pub_resp.json()["id"]
print(f"SUCCESS! Published Post ID: {post_id}")

# Step 4: Fetch Live Post Permalink
permalink_url = f"https://graph.facebook.com/v22.0/{post_id}?fields=id,permalink,timestamp,caption&access_token={ACCESS_TOKEN}"
perm_resp = requests.get(permalink_url, timeout=10)
if perm_resp.status_code == 200:
    post_info = perm_resp.json()
    print("==================================================")
    print("LIVE POST PERMALINK:")
    print(post_info.get("permalink"))
    print("==================================================")

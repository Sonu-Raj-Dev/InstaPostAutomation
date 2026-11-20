import os
import requests
from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
    print("Injected native Windows certificate store into SSL.")
except Exception as e:
    print("Truststore error:", e)

load_dotenv()

token = os.getenv("META_ACCESS_TOKEN", "").strip()
print(f"Token present (length: {len(token)})")

# Disable insecure request warnings if fallback is needed
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Query /me
url = f"https://graph.facebook.com/v22.0/me?access_token={token}"
try:
    resp = requests.get(url, timeout=10)
    print("User /me response:", resp.status_code, resp.json())
except Exception as e:
    # Try with verify=False if corporate proxy blocks certifi
    try:
        resp = requests.get(url, timeout=10, verify=False)
        print("User /me response (verify=False):", resp.status_code, resp.json())
    except Exception as e2:
        print("User /me error:", e2)

# 2. Query /me/accounts
url = f"https://graph.facebook.com/v22.0/me/accounts?fields=id,name,access_token,instagram_business_account{{id,username,name,profile_picture_url}}&access_token={token}"
try:
    resp = requests.get(url, timeout=10, verify=False)
    print("Pages /me/accounts response:", resp.status_code, resp.json())
except Exception as e:
    print("Pages /me/accounts error:", e)

import os, time, base64, requests

EBAY_ENV = os.getenv("EBAY_ENV", "PROD")
OAUTH_BASE = "https://api.ebay.com/identity/v1/oauth2/token" if EBAY_ENV == "PROD" else "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
CLIENT_ID = os.getenv("EBAY_APP_ID")
CLIENT_SECRET = os.getenv("EBAY_CERT_ID")
REFRESH_TOKEN = os.getenv("EBAY_REFRESH_TOKEN")

def _basic_auth():
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    return base64.b64encode(raw).decode()

_access_token = None
_expires_at = 0

SELL_SCOPES = "https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.marketing.readonly https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly https://api.ebay.com/oauth/api_scope/sell.account.readonly https://api.ebay.com/oauth/api_scope/sell.finance.readonly https://api.ebay.com/oauth/api_scope/sell.analytics.readonly https://api.ebay.com/oauth/api_scope/sell.marketplace.insights.readonly https://api.ebay.com/oauth/api_scope/sell.item.readonly https://api.ebay.com/oauth/api_scope/sell.inventory.readonly https://api.ebay.com/oauth/api_scope/sell.feed.readonly"

def get_access_token():
    global _access_token, _expires_at
    if _access_token and time.time() < _expires_at - 60:
        return _access_token
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "scope": SELL_SCOPES
    }
    headers = {
        "Authorization": f"Basic {_basic_auth()}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    r = requests.post(OAUTH_BASE, data=data, headers=headers, timeout=30)
    r.raise_for_status()
    payload = r.json()
    _access_token = payload["access_token"]
    _expires_at = time.time() + payload.get("expires_in", 7200)
    return _access_token

import requests
from ebay_auth import get_access_token

BASE = "https://api.ebay.com/sell/inventory/v1"

def _hdrs():
    return {"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json", "Accept": "application/json"}

def get_offers_for_sku(sku):
    r = requests.get(f"{BASE}/offer?sku={sku}", headers=_hdrs(), timeout=30)
    r.raise_for_status()
    return r.json().get("offers", [])

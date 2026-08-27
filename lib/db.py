"""
lib/db.py — thin wrapper around Vercel KV (Upstash Redis REST API)
------------------------------------------------------------------------------------------
Vercel functions have zero memory of their own — every call starts blank. This gives
us a real, permanent place to store user accounts and API keys.

Setup (one-time, done in Vercel dashboard, not code):
    Vercel Project -> Storage tab -> Create Database -> KV
    This automatically adds KV_REST_API_URL and KV_REST_API_TOKEN as env vars.
"""

import os
import requests

KV_URL = os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN")


def _headers():
    return {"Authorization": f"Bearer {KV_TOKEN}"}


def kv_set(key: str, value: str):
    r = requests.post(f"{KV_URL}/set/{key}", headers=_headers(), data=value, timeout=10)
    r.raise_for_status()
    return r.json()


def kv_get(key: str):
    r = requests.get(f"{KV_URL}/get/{key}", headers=_headers(), timeout=10)
    r.raise_for_status()
    result = r.json().get("result")
    return result  # None if key doesn't exist


def kv_delete(key: str):
    r = requests.post(f"{KV_URL}/del/{key}", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

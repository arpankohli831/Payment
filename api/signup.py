"""
api/signup.py — create a new account, get back a personal API key

POST /api/signup   { "email": "...", "password": "..." }
    -> { "api_key": "..." }

Password is never stored in plain text — only a salted hash. The API key is what
the user's bot will use to call the verify endpoint (built in a later stage).
"""

import os
import json
import hashlib
import secrets
from http.server import BaseHTTPRequestHandler

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from lib.db import kv_get, kv_set


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""

        if not email or "@" not in email:
            self._reply(400, {"error": "valid email is required"})
            return
        if len(password) < 8:
            self._reply(400, {"error": "password must be at least 8 characters"})
            return

        existing = kv_get(f"user:{email}")
        if existing:
            self._reply(409, {"error": "an account with this email already exists"})
            return

        salt = secrets.token_hex(16)
        password_hash = hash_password(password, salt)
        api_key = secrets.token_urlsafe(32)

        user_record = {
            "email": email,
            "salt": salt,
            "password_hash": password_hash,
            "api_key": api_key,
        }

        kv_set(f"user:{email}", json.dumps(user_record))
        kv_set(f"apikey:{api_key}", email)  # fast lookup: api_key -> email

        self._reply(200, {"api_key": api_key})

    def _reply(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

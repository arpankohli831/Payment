"""
api/login.py — verify email + password, get back your existing API key

POST /api/login   { "email": "...", "password": "..." }
    -> { "api_key": "..." }
"""

import os
import json
import hashlib
from http.server import BaseHTTPRequestHandler

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from lib.db import kv_get


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""

        raw = kv_get(f"user:{email}")
        if not raw:
            self._reply(401, {"error": "invalid email or password"})
            return

        user = json.loads(raw)
        expected_hash = hash_password(password, user["salt"])

        if expected_hash != user["password_hash"]:
            self._reply(401, {"error": "invalid email or password"})
            return

        self._reply(200, {"api_key": user["api_key"]})

    def _reply(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

"""
api/connect-gmail.py — user connects their own Gmail for payment checking

POST /api/connect-gmail
    { "api_key": "...", "gmail_user": "...", "gmail_app_password": "..." }
    -> { "connected": true }

Their Gmail app password is encrypted before being saved — never stored in plain text.
"""

import os
import json
from http.server import BaseHTTPRequestHandler

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from lib.db import kv_get, kv_set
from lib.crypto import encrypt


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        api_key = body.get("api_key")
        gmail_user = body.get("gmail_user")
        gmail_app_password = body.get("gmail_app_password")

        if not api_key or not gmail_user or not gmail_app_password:
            self._reply(400, {"error": "api_key, gmail_user, and gmail_app_password are all required"})
            return

        email = kv_get(f"apikey:{api_key}")
        if not email:
            self._reply(401, {"error": "invalid api_key"})
            return

        raw = kv_get(f"user:{email}")
        user = json.loads(raw)

        user["gmail_user"] = gmail_user
        user["gmail_app_password_encrypted"] = encrypt(gmail_app_password)

        kv_set(f"user:{email}", json.dumps(user))

        self._reply(200, {"connected": True})

    def _reply(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

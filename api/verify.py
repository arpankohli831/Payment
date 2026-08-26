"""
api/verify.py — standalone verify endpoint (optional, for calling from elsewhere)

POST /api/verify   { "api_key": "...", "amount": 1 }  ->  { "verified": true/false }

Only counts payment emails received in the last 60 seconds (see lib/gmail_check.py).

ENV VARS:
    GMAIL_USER, GMAIL_APP_PASSWORD, VERIFY_API_KEY
"""

import os
import json
from http.server import BaseHTTPRequestHandler

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from lib.gmail_check import check_gmail_for_amount

VERIFY_API_KEY = os.environ.get("VERIFY_API_KEY")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if body.get("api_key") != VERIFY_API_KEY:
            self._reply(401, {"verified": False, "error": "invalid api_key"})
            return

        amount = body.get("amount")
        if amount is None:
            self._reply(400, {"verified": False, "error": "amount is required"})
            return

        try:
            amount = float(amount)
            verified = check_gmail_for_amount(amount)
            self._reply(200, {"verified": verified, "amount": amount})
        except Exception as e:
            self._reply(500, {"verified": False, "error": str(e)})

    def do_GET(self):
        self._reply(200, {"service": "verify API", "status": "running"})

    def _reply(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

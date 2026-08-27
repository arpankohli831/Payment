"""
api/my-scan.py — per-user payment checker (each api_key checks only their own Gmail)

GET /api/my-scan?api_key=THEIR_KEY
    -> { "amounts": [10.0, 25.5, ...] }

This is the per-user version of scan.py — instead of always checking YOUR Gmail,
it looks up which user the api_key belongs to, decrypts THEIR Gmail credentials,
and checks THEIR inbox.
"""

import os
import re
import json
import imaplib
import email as email_lib
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from lib.db import kv_get
from lib.crypto import decrypt

FAMPAY_SENDER_FILTER = "famapp"
AMOUNT_REGEX = r"(?:successfully received|received|sent).*?(?:Rs\.?|₹)\s?([\d,]+\.?\d*)"


def fetch_unseen_amounts(gmail_user, gmail_app_password):
    amounts = []
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(gmail_user, gmail_app_password)
    imap.select("inbox")

    status, data = imap.search(None, f'(UNSEEN FROM "{FAMPAY_SENDER_FILTER}")')
    ids = data[0].split()

    for msg_id in ids:
        _, msg_data = imap.fetch(msg_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw_email)

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ["text/plain", "text/html"]:
                    try:
                        body += part.get_payload(decode=True).decode(errors="ignore") + " "
                    except Exception:
                        pass
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body)

        match = re.search(AMOUNT_REGEX, body, re.IGNORECASE | re.DOTALL)
        if match:
            amounts.append(float(match.group(1).replace(",", "")))

    imap.logout()
    return amounts


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        api_key = query.get("api_key", [None])[0]

        if not api_key:
            self._reply(400, {"error": "api_key is required"})
            return

        email = kv_get(f"apikey:{api_key}")
        if not email:
            self._reply(401, {"error": "invalid api_key"})
            return

        raw = kv_get(f"user:{email}")
        user = json.loads(raw)

        gmail_user = user.get("gmail_user")
        gmail_app_password_encrypted = user.get("gmail_app_password_encrypted")

        if not gmail_user or not gmail_app_password_encrypted:
            self._reply(400, {"error": "no Gmail connected yet — call /api/connect-gmail first"})
            return

        try:
            gmail_app_password = decrypt(gmail_app_password_encrypted)
            amounts = fetch_unseen_amounts(gmail_user, gmail_app_password)
            self._reply(200, {"amounts": amounts})
        except Exception as e:
            self._reply(500, {"error": str(e), "amounts": []})

    def _reply(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

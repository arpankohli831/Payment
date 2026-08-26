"""
api/scan.py — returns amounts from recent unread FamApp payment emails
------------------------------------------------------------------------------------------
REVERTED: the stricter domain+DKIM check broke a real payment (rejected a genuine ₹47
FamApp email), so it's removed. Back to the version that was actually confirmed working.

GET /api/scan?api_key=YOUR_KEY
    -> { "amounts": [10.0, 25.5, ...] }

Uses UNSEEN — fetching an email marks it read automatically, so a matched email can
never be returned twice.

ENV VARS (Vercel dashboard):
    GMAIL_USER, GMAIL_APP_PASSWORD, VERIFY_API_KEY
"""

import os
import re
import json
import imaplib
import email as email_lib
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
VERIFY_API_KEY = os.environ.get("VERIFY_API_KEY")

FAMPAY_SENDER_FILTER = "famapp"
AMOUNT_REGEX = r"(?:successfully received|received|sent).*?(?:Rs\.?|₹)\s?([\d,]+\.?\d*)"


def fetch_unseen_amounts():
    amounts = []
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    imap.select("inbox")

    status, data = imap.search(None, f'(UNSEEN FROM "{FAMPAY_SENDER_FILTER}")')
    ids = data[0].split()

    for msg_id in ids:
        _, msg_data = imap.fetch(msg_id, "(RFC822)")  # fetching marks it \Seen automatically
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

        if api_key != VERIFY_API_KEY:
            self._reply(401, {"error": "invalid api_key"})
            return

        try:
            amounts = fetch_unseen_amounts()
            self._reply(200, {"amounts": amounts})
        except Exception as e:
            self._reply(500, {"error": str(e), "amounts": []})

    def _reply(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

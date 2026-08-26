"""
api/scan.py — returns amounts from recent unread FamApp payment emails (HARDENED)
------------------------------------------------------------------------------------------
Only bot.py side that changes: NONE. This file lives entirely on Vercel — bot.py just
calls it over HTTPS and trusts the response, so all the anti-fake-payment protection
below is invisible to bot.py and requires zero changes there.

FAKE-PAYMENT PROTECTIONS ADDED:
  1. Exact sender domain match — was a loose "contains famapp" check before, which a
     spoofed address like noreply@famapp-verify.com would have passed. Now only the
     real domain counts.
  2. DKIM authentication check — verifies Gmail cryptographically confirmed the email
     really came from FamApp's servers, not just that it *claims* to be from FamApp.
     This is the strongest protection: even a perfectly-faked "From" address can't
     pass DKIM without actually controlling FamApp's mail servers.

⚠️ FAMPAY_SENDER_DOMAIN below is my best guess based on the support email address shown
in your FamApp email screenshot (support@famapp.in). Please confirm this is correct —
if a real payment email ever gets rejected, check the exact "From:" address of that
email and update FAMPAY_SENDER_DOMAIN to match exactly.

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

FAMPAY_SENDER_DOMAIN = "famapp.in"  # confirm this matches your real payment emails
AMOUNT_REGEX = r"(?:successfully received|received|sent).*?(?:Rs\.?|₹)\s?([\d,]+\.?\d*)"


def sender_domain_is_exact(msg) -> bool:
    """True only if the From address's domain exactly matches FAMPAY_SENDER_DOMAIN."""
    from_header = msg.get("From", "")
    match = re.search(r"@([\w.-]+)>?$", from_header.strip())
    if not match:
        return False
    domain = match.group(1).lower()
    return domain == FAMPAY_SENDER_DOMAIN.lower()


def dkim_passed(msg) -> bool:
    """
    True if Gmail's own header confirms this email passed DKIM authentication for
    the expected domain. This is checked in addition to (not instead of) the exact
    sender match above — both must pass.
    """
    auth_results = msg.get("Authentication-Results", "") or ""
    auth_results = auth_results.lower()
    if "dkim=pass" not in auth_results:
        return False
    if FAMPAY_SENDER_DOMAIN.lower() not in auth_results:
        return False
    return True


def fetch_unseen_amounts():
    amounts = []
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    imap.select("inbox")

    # broad search first (domain-only search isn't reliably supported across all
    # IMAP setups), exact verification happens per-message below
    status, data = imap.search(None, '(UNSEEN FROM "famapp")')
    ids = data[0].split()

    for msg_id in ids:
        _, msg_data = imap.fetch(msg_id, "(RFC822)")  # fetching marks it \Seen automatically
        raw_email = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw_email)

        # --- reject anything that isn't provably a real FamApp email ---
        if not sender_domain_is_exact(msg):
            continue
        if not dkim_passed(msg):
            continue

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

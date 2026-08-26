"""
lib/gmail_check.py — shared payment-verification logic
------------------------------------------------------------------------------------------
Both api/webhook.py (the bot) and api/verify.py (standalone API) import this,
so there's exactly ONE place that knows how to check Gmail. Change the regex
or sender filter here and both use the update automatically.
"""

import os
import re
import imaplib
import email as email_lib

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

FAMPAY_SENDER_FILTER = "famapp"
AMOUNT_REGEX = r"successfully received\s*(?:Rs\.?|₹)\s?([\d,]+\.?\d*)"


def check_gmail_for_amount(expected_amount: float) -> bool:
    """Returns True if a FamApp email confirming this amount exists in the inbox."""
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    imap.select("inbox")

    status, data = imap.search(None, f'(FROM "{FAMPAY_SENDER_FILTER}")')
    ids = data[0].split()[-15:]  # only check the last 15 emails, keeps it fast

    found = False
    for msg_id in ids:
        _, msg_data = imap.fetch(msg_id, "(RFC822)")
        msg = email_lib.message_from_bytes(msg_data[0][1])

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        match = re.search(AMOUNT_REGEX, body, re.IGNORECASE)
        if match:
            amount = float(match.group(1).replace(",", ""))
            if abs(amount - expected_amount) < 0.01:
                found = True

    imap.logout()
    return found

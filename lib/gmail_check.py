"""
lib/gmail_check.py — shared payment-verification logic
------------------------------------------------------------------------------------------
Rule: when the user taps "I've Paid", only emails that arrived in the last
WINDOW_SECONDS (default 60) count as a match. Anything older is ignored — so an
old payment from a past test can never confirm a new /pay request.

A matched email is also \\Flagged so it can't be reused a second time even within
that same 60-second window (e.g. if the button gets tapped twice quickly).
"""

import os
import re
import imaplib
import email as email_lib
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

FAMPAY_SENDER_FILTER = "famapp"
AMOUNT_REGEX = r"successfully received\s*(?:Rs\.?|₹)\s?([\d,]+\.?\d*)"

WINDOW_SECONDS = 60  # only emails received within this many seconds of the button tap count


def check_gmail_for_amount(expected_amount: float) -> bool:
    """
    Returns True only if a FamApp email confirming this amount arrived within
    the last WINDOW_SECONDS (checked from right now, at call time), and hasn't
    already been used to confirm a previous check (via the \\Flagged marker).

    Note: FamApp emails can take a little time to arrive after a real payment.
    If this returns False right after paying, wait a few seconds and tap
    "I've Paid" again — that's normal, not a rejection of a real payment.
    """
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    imap.select("inbox")

    # UNFLAGGED = not yet used to confirm a previous check
    status, data = imap.search(None, f'(FROM "{FAMPAY_SENDER_FILTER}" UNFLAGGED)')
    ids = data[0].split()[-15:]  # only need to look at the most recent few

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=WINDOW_SECONDS)
    found = False

    for msg_id in ids:
        _, msg_data = imap.fetch(msg_id, "(RFC822)")
        msg = email_lib.message_from_bytes(msg_data[0][1])

        try:
            email_dt = parsedate_to_datetime(msg.get("Date"))
            if email_dt.tzinfo is None:
                email_dt = email_dt.replace(tzinfo=timezone.utc)
            if email_dt < cutoff:
                continue  # older than 60 seconds ago — ignore it
        except Exception:
            continue  # can't parse the date, skip it to be safe

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
                imap.store(msg_id, "+FLAGS", "\\Flagged")  # mark used, can't be reused
                break

    imap.logout()
    return found

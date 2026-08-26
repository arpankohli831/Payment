"""
api/webhook.py — Telegram bot (webhook mode)
------------------------------------------------------------------------------------------
Features:
  - "I've Paid ✅" tap shows a quick "⏳ Checking..." animation on the caption
  - On success: QR message is deleted, a clean "✅ Payment added successfully!" message
    is sent instead
  - On failure: caption updates to "❌ Payment not found" with a retry button
  - QR expires 5 minutes after creation — after that, tapping the button just shows
    "⌛ QR expired, send /pay again" without wasting a Gmail check (saves time + avoids
    checking against a long-stale order)
  - 10-second cooldown per chat between Gmail checks — stops rapid button-tapping from
    triggering many Gmail logins in a row, which protects the account from being flagged
    as suspicious by Google

check_gmail_for_amount() only looks at emails from the last 60 seconds at tap-time
(see lib/gmail_check.py) — old emails from past tests/payments can never match.

Also deduplicates Telegram's retried webhook calls so a slow response doesn't cause
duplicate messages.

ENV VARS (Vercel dashboard):
    BOT_TOKEN, GMAIL_USER, GMAIL_APP_PASSWORD, UPI_ID, UPI_NAME

ONE-TIME SETUP after deploying:
    https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://YOURAPP.vercel.app/api/webhook
"""

import os
import json
import time
from io import BytesIO
from http.server import BaseHTTPRequestHandler

import requests
import qrcode

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from lib.gmail_check import check_gmail_for_amount

BOT_TOKEN = os.environ.get("BOT_TOKEN")
UPI_ID = os.environ.get("UPI_ID", "yourid@fam")
UPI_NAME = os.environ.get("UPI_NAME", "YOUR NAME")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

QR_EXPIRY_SECONDS = 300  # 5 minutes
COOLDOWN_SECONDS = 10    # minimum gap between Gmail checks per chat, protects your Gmail account

# Best-effort in-memory dedupe. Vercel functions can be reused between invocations,
# so this catches most duplicate retries within the same warm instance (not perfect
# across cold starts, but eliminates the vast majority of duplicate replies).
_processed_update_ids = set()
_last_check_time = {}   # chat_id -> unix timestamp of last Gmail check


def tg_send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)


def tg_send_photo(chat_id, photo_bytes, caption, reply_markup):
    files = {"photo": ("qr.png", photo_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption, "reply_markup": json.dumps(reply_markup)}
    requests.post(f"{TG_API}/sendPhoto", data=data, files=files, timeout=15)


def tg_edit_caption(chat_id, message_id, caption, reply_markup=None):
    data = {"chat_id": chat_id, "message_id": message_id, "caption": caption}
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{TG_API}/editMessageCaption", json=data, timeout=10)


def tg_delete_message(chat_id, message_id):
    requests.post(f"{TG_API}/deleteMessage",
                  json={"chat_id": chat_id, "message_id": message_id}, timeout=10)


def tg_answer_callback(callback_query_id, text):
    requests.post(f"{TG_API}/answerCallbackQuery",
                  json={"callback_query_id": callback_query_id, "text": text}, timeout=10)


def make_upi_qr(amount, order_id):
    upi_link = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amount:.2f}&cu=INR&tn={order_id}"
    img = qrcode.make(upi_link)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def order_age_seconds(order_id):
    """order_id looks like order_<chat_id>_<unix_timestamp>."""
    try:
        created_at = float(order_id.rsplit("_", 1)[-1])
        return time.time() - created_at
    except (ValueError, IndexError):
        return QR_EXPIRY_SECONDS + 1  # if we can't parse it, treat as expired to be safe


def handle_update(update):
    update_id = update.get("update_id")
    if update_id in _processed_update_ids:
        return  # already handled this exact update, Telegram just retried it
    _processed_update_ids.add(update_id)

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/start"):
            tg_send_message(chat_id, "Send /pay <amount> to generate a UPI payment QR, e.g. /pay 10")

        elif text.startswith("/pay"):
            parts = text.split()
            amount = float(parts[1]) if len(parts) > 1 else 1.00
            order_id = f"order_{chat_id}_{int(time.time())}"

            qr_bytes = make_upi_qr(amount, order_id)
            caption = (
                f"₹{amount:.2f} payment\nRef: {order_id}\n\n"
                f"Scan with any UPI app, then tap the button below.\n"
                f"⏱ Valid for 5 minutes."
            )
            keyboard = {"inline_keyboard": [[
                {"text": "I've Paid ✅", "callback_data": f"check:{amount}:{order_id}"}
            ]]}
            tg_send_photo(chat_id, qr_bytes, caption, keyboard)

    elif "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        _, amount_str, order_id = cq["data"].split(":", 2)
        amount = float(amount_str)

        # --- expiry check first, before wasting a Gmail check on a stale QR ---
        if order_age_seconds(order_id) > QR_EXPIRY_SECONDS:
            tg_answer_callback(cq["id"], "This QR has expired")
            tg_edit_caption(
                chat_id, message_id,
                f"⌛ QR expired\nRef: {order_id}\n\nSend /pay {amount:g} again to get a fresh one.",
                reply_markup={"inline_keyboard": []}  # remove the button
            )
            return

        # --- cooldown check: stop rapid repeated taps from hammering Gmail ---
        now = time.time()
        last_check = _last_check_time.get(chat_id, 0)
        elapsed = now - last_check
        if elapsed < COOLDOWN_SECONDS:
            wait_more = round(COOLDOWN_SECONDS - elapsed)
            tg_answer_callback(cq["id"], f"Please wait {wait_more}s before checking again")
            return
        _last_check_time[chat_id] = now

        # --- quick "checking" animation ---
        tg_answer_callback(cq["id"], "Checking...")
        tg_edit_caption(
            chat_id, message_id,
            f"⏳ Checking payment...\nRef: {order_id}\nAmount: ₹{amount:.2f}"
        )

        try:
            paid = check_gmail_for_amount(amount)  # only checks last 60 seconds of mail
        except Exception as e:
            tg_edit_caption(chat_id, message_id, f"⚠️ Check failed: {e}")
            return

        if paid:
            tg_delete_message(chat_id, message_id)  # remove the QR entirely
            tg_send_message(chat_id, f"✅ Payment added successfully!\nOrder: {order_id}\nAmount: ₹{amount:.2f}")
        else:
            keyboard = {"inline_keyboard": [[
                {"text": "I've Paid ✅", "callback_data": f"check:{amount}:{order_id}"}
            ]]}
            tg_edit_caption(
                chat_id, message_id,
                f"❌ Payment not found\nRef: {order_id}\nAmount: ₹{amount:.2f}\n\n"
                f"Pay first (or wait a few seconds for the email), then tap again.",
                reply_markup=keyboard
            )


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        update = json.loads(self.rfile.read(length))

        try:
            handle_update(update)
        except Exception as e:
            print("handler error:", e)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "bot webhook alive"}')

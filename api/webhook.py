"""
api/webhook.py — Telegram bot (webhook mode, connects to lib/gmail_check.py)
------------------------------------------------------------------------------------------
This IS your Telegram bot. Vercel can't run infinity_polling() (needs a forever-running
process), so Telegram sends updates to this URL instead, and this file replies using
plain HTTP calls to Telegram's API.

Flow:
  /pay <amount>  -> generates UPI QR, sends it + an "I've Paid" button
  button tapped  -> calls check_gmail_for_amount() from lib/gmail_check.py, replies

ENV VARS (set in Vercel dashboard -> Settings -> Environment Variables):
    BOT_TOKEN
    GMAIL_USER
    GMAIL_APP_PASSWORD
    UPI_ID
    UPI_NAME

ONE-TIME SETUP after deploying, run once (browser or curl):
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


def tg_send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)


def tg_send_photo(chat_id, photo_bytes, caption, reply_markup):
    files = {"photo": ("qr.png", photo_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption, "reply_markup": json.dumps(reply_markup)}
    requests.post(f"{TG_API}/sendPhoto", data=data, files=files, timeout=15)


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


def handle_update(update):
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
            caption = f"₹{amount:.2f} payment\nRef: {order_id}\n\nScan with any UPI app, then tap the button below."
            keyboard = {"inline_keyboard": [[
                {"text": "I've Paid ✅", "callback_data": f"check:{amount}:{order_id}"}
            ]]}
            tg_send_photo(chat_id, qr_bytes, caption, keyboard)

    elif "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        _, amount_str, order_id = cq["data"].split(":", 2)
        amount = float(amount_str)

        tg_answer_callback(cq["id"], "Checking...")

        try:
            paid = check_gmail_for_amount(amount)   # <-- this is the "connection" to the verification logic
        except Exception as e:
            tg_send_message(chat_id, f"⚠️ Check failed: {e}")
            return

        if paid:
            tg_send_message(chat_id, f"✅ Payment verified!\nOrder: {order_id}\nAmount: ₹{amount:.2f}")
        else:
            tg_send_message(chat_id, "❌ No matching payment found yet. Pay first, then tap again.")


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

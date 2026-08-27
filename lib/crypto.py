"""
lib/crypto.py — encrypt/decrypt Gmail app passwords before storing them
------------------------------------------------------------------------------------------
Never store a user's Gmail app password in plain text, even in your own database.
This uses Fernet symmetric encryption — only your server (with ENCRYPTION_KEY) can
decrypt it back.

SETUP (one-time): generate a key and add it as an env var in Vercel:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    -> copy the output, add as ENCRYPTION_KEY in Vercel env vars
"""

import os
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")


def _fernet():
    return Fernet(ENCRYPTION_KEY.encode())


def encrypt(plain_text: str) -> str:
    return _fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    return _fernet().decrypt(cipher_text.encode()).decode()

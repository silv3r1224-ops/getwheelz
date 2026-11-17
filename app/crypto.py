"""Encrypted ids for URLs.

Every id that used to appear in a link (/workshops/12, /bookings/7/receipt, profile tokens, ...) is now
sealed with authenticated encryption (ChaCha20-Poly1305), so a visitor cannot read it, guess the next
one, edit it or reuse a token meant for another kind of record.

* The key is derived from SECRET_KEY with HKDF, so no extra secret has to be configured.
* The "purpose" ("workshop", "booking", ...) is bound to the token as associated data: a booking token
  is rejected where a workshop token is expected.
* The nonce is derived from the purpose and the id (a synthetic-IV construction), so the same record always
  gets the same link. That keeps URLs stable for caching and bookmarks; the only thing it reveals is
  "these two links point at the same record".
* Tokens are short (about 40 characters) and URL safe.
* Opening a token never raises: a wrong, edited or foreign token simply returns None (the route then answers 404).

Changing SECRET_KEY invalidates every link that was handed out before, which is the intended behaviour.
"""
import base64
import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_KEYS = {}


def _derive(secret):
    if isinstance(secret, str):
        secret = secret.encode()
    if secret in _KEYS:
        return _KEYS[secret]
    enc = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"getwheelz-url-v2", info=b"aead").derive(secret)
    mac = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"getwheelz-url-v2", info=b"nonce").derive(secret)
    _KEYS[secret] = (ChaCha20Poly1305(enc), mac)
    return _KEYS[secret]


def _key():
    try:
        from flask import current_app

        secret = current_app.secret_key
    except RuntimeError:  # no app context (scripts, tests): same key the app uses
        import os

        secret = os.environ["SECRET_KEY"]
    return _derive(secret)


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(purpose, value):
    """Encrypt a small non-negative integer for use in a URL."""
    n = int(value)
    if n < 0:
        raise ValueError("ids are never negative")
    aead, mac = _key()
    plain = n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big")
    aad = purpose.encode()
    nonce = hmac.new(mac, aad + b"\x00" + plain, hashlib.sha256).digest()[:12]
    return _b64e(nonce + aead.encrypt(nonce, plain, aad))


def open_(purpose, token):
    """Decrypt a token made by seal(); None when it is not a valid token for this purpose."""
    try:
        if not token or len(token) > 120:
            return None
        raw = _b64d(token)
        if len(raw) < 12 + 1 + 16 or len(raw) > 12 + 8 + 16:
            return None
        aead, _ = _key()
        plain = aead.decrypt(raw[:12], raw[12:], purpose.encode())
        return int.from_bytes(plain, "big")
    except Exception:
        return None


# ---- Werkzeug URL converter:  <sealed("workshop"):w_id>  -------------------------------------------------
from werkzeug.routing import BaseConverter, ValidationError  # noqa: E402


class SealedConverter(BaseConverter):
    """In a route, the part of the URL is an encrypted id; the view function still receives a plain int.
    url_for(..., w_id=12) seals it again, so no template or view has to change."""

    regex = r"[A-Za-z0-9_-]{20,64}"
    part_isolating = True

    def __init__(self, map, purpose="id"):
        super().__init__(map)
        self.purpose = purpose

    def to_python(self, value):
        n = open_(self.purpose, value)
        if n is None:
            raise ValidationError()
        return n

    def to_url(self, value):
        return seal(self.purpose, value)

"""Short-lived signed links.

Browsers cannot attach an ``Authorization`` header to a file download or to a direct
upload, so those two requests carry a signed, expiring token instead. A token names
one storage object and one purpose, so an upload link cannot be replayed as a
download link, nor pointed at a different file.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class InvalidLink(Exception):
    """The token is malformed, forged, expired, or issued for a different purpose."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def sign(payload: dict[str, Any], *, purpose: str, secret: str, ttl_seconds: int) -> str:
    claims = {**payload, "p": purpose, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_signature(body, secret)}"


def unsign(token: str, *, purpose: str, secret: str) -> dict[str, Any]:
    body, separator, signature = token.partition(".")
    if not separator or not hmac.compare_digest(signature, _signature(body, secret)):
        raise InvalidLink("invalid signature")
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidLink("malformed token") from error
    if claims.get("p") != purpose:
        raise InvalidLink("wrong purpose")
    if int(claims.get("exp", 0)) < time.time():
        raise InvalidLink("expired")
    return claims

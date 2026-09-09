"""Device claim, cookie/bearer auth, and per-device rate limits."""
import hashlib, hmac, os, secrets, time
from fastapi import Request

from . import db
from .config import share_secret, share_enabled, share_rate, ingest_secret

COOKIE = "tribli_share"
_hits: dict[str, list[float]] = {}


def reset_rate_limits():
    _hits.clear()


def hash_token(token: str) -> str:
    secret = share_secret() or "unconfigured"
    return hashlib.sha256((secret + ":" + (token or "")).encode("utf-8")).hexdigest()


def issue_device_token(label: str = "") -> str:
    token = secrets.token_urlsafe(32)
    db.put_share_device(hash_token(token), label=label)
    return token


def _check_rate(key: str) -> bool:
    now = time.time()
    window = 3600.0
    cap = max(1, share_rate())
    bucket = [t for t in _hits.get(key, []) if now - t < window]
    if len(bucket) >= cap:
        _hits[key] = bucket
        return False
    bucket.append(now)
    _hits[key] = bucket
    return True


def rate_ok(device_hash: str, ip: str) -> bool:
    return _check_rate("d:" + device_hash) and _check_rate("ip:" + (ip or "0"))


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    hdr = request.headers.get("x-tribli-share-token", "").strip()
    if hdr:
        return hdr
    return (request.cookies.get(COOKIE) or "").strip()


def authenticate_share(request: Request) -> str | None:
    """Return device token hash, or None."""
    if not share_enabled():
        return None
    if not share_secret():
        return None
    token = _token_from_request(request)
    if not token:
        return None
    # Operator secret is for claim / ingest only — not a share credential.
    if hmac.compare_digest(token, share_secret()):
        return None
    h = hash_token(token)
    if not db.share_device_ok(h):
        return None
    return h


def authenticate_operator(request: Request) -> bool:
    expected = ingest_secret()
    if not expected:
        return False
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        got = auth.split(" ", 1)[1].strip()
        return hmac.compare_digest(got, expected)
    q = request.query_params.get("token") or ""
    return hmac.compare_digest(q, expected) if q else False


def claim_secret_ok(secret: str) -> bool:
    expected = share_secret()
    if not expected or not secret:
        return False
    return hmac.compare_digest(secret.strip(), expected)

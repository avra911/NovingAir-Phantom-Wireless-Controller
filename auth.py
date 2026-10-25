"""Single-user authentication: scrypt password hash + signed expiring bearer tokens.

Generate the hash for .env with:  python auth.py
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
TOKEN_TTL_SECONDS = 30 * 24 * 3600

MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

PUBLIC_PATHS = {"/", "/auth/login"}

_failures: dict[str, list[float]] = {}


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _b64d(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=_b64d(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _username() -> str:
    return os.environ.get("AUTH_USERNAME", "")


def _password_hash() -> str:
    return os.environ.get("AUTH_PASSWORD_HASH", "")


def auth_enabled() -> bool:
    return bool(_username() and _password_hash())


def _signing_key() -> bytes:
    # Rotating AUTH_SECRET or changing the password invalidates every issued token.
    return (os.environ.get("AUTH_SECRET") or _password_hash()).encode()


def issue_token(username: str) -> str:
    payload = _b64e(json.dumps({"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS}).encode())
    sig = _b64e(hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str) -> bool:
    try:
        payload, sig = token.split(".")
        expected = _b64e(hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return False
        claims = json.loads(_b64d(payload))
        return claims.get("sub") == _username() and claims.get("exp", 0) > time.time()
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def _locked_out(client: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(client, []) if now - t < LOCKOUT_SECONDS]
    _failures[client] = recent
    return len(recent) >= MAX_FAILURES


def login(client: str, username: str, password: str) -> str:
    if not auth_enabled():
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if _locked_out(client):
        raise HTTPException(status_code=429, detail="Too many failed attempts, try again later")

    # Always run the hash so a wrong username takes as long as a wrong password.
    password_ok = verify_password(password, _password_hash())
    username_ok = hmac.compare_digest(username.encode(), _username().encode())
    if not (password_ok and username_ok):
        _failures.setdefault(client, []).append(time.time())
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _failures.pop(client, None)
    return issue_token(_username())


async def require_auth(request: Request) -> None:
    if not auth_enabled() or request.url.path in PUBLIC_PATHS:
        return
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not verify_token(token):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


if __name__ == "__main__":
    user = input("Username: ")
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    print("\nAdd to .env (single-quote the hash, it contains '$'):")
    print(f"AUTH_USERNAME={user}")
    print(f"AUTH_PASSWORD_HASH='{hash_password(pw)}'")

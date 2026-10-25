import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import auth


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", auth.hash_password("s3cret"))
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    auth._failures.clear()


def _request(path="/state", token=None):
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "path": path, "headers": headers})


def test_hash_is_salted_and_verifies():
    first, second = auth.hash_password("pw"), auth.hash_password("pw")
    assert first != second
    assert auth.verify_password("pw", first)
    assert not auth.verify_password("other", first)
    assert not auth.verify_password("pw", "garbage")


def test_login_returns_valid_token():
    assert auth.verify_token(auth.login("1.1.1.1", "admin", "s3cret"))


@pytest.mark.parametrize("user,pw", [("admin", "bad"), ("nobody", "s3cret")])
def test_login_rejects_bad_credentials(user, pw):
    with pytest.raises(HTTPException) as exc:
        auth.login("1.1.1.1", user, pw)
    assert exc.value.status_code == 401


def test_login_locks_out_after_repeated_failures():
    for _ in range(auth.MAX_FAILURES):
        with pytest.raises(HTTPException):
            auth.login("2.2.2.2", "admin", "bad")
    with pytest.raises(HTTPException) as exc:
        auth.login("2.2.2.2", "admin", "s3cret")
    assert exc.value.status_code == 429


def test_tampered_and_expired_tokens_are_rejected(monkeypatch):
    token = auth.issue_token("admin")
    payload, sig = token.split(".")
    assert not auth.verify_token(f"{payload}.{sig[:-2]}AA")
    assert not auth.verify_token("not-a-token")

    future = time.time() + auth.TOKEN_TTL_SECONDS + 1
    monkeypatch.setattr(auth.time, "time", lambda: future)
    assert not auth.verify_token(token)


def test_changing_password_invalidates_tokens(monkeypatch):
    token = auth.issue_token("admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", auth.hash_password("new"))
    assert not auth.verify_token(token)


@pytest.mark.asyncio
async def test_require_auth_guards_private_paths_only():
    with pytest.raises(HTTPException) as exc:
        await auth.require_auth(_request("/command/BOOST"))
    assert exc.value.status_code == 401

    await auth.require_auth(_request("/"))
    await auth.require_auth(_request("/auth/login"))
    await auth.require_auth(_request("/state", auth.issue_token("admin")))


@pytest.mark.asyncio
async def test_require_auth_is_open_when_unconfigured(monkeypatch):
    monkeypatch.delenv("AUTH_USERNAME")
    await auth.require_auth(_request("/command/BOOST"))

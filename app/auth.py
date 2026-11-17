"""Authentication, password hashing, and HMAC-signed persistent sessions."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from typing import Optional

from fastapi import HTTPException, Request

from app.config import DATA_DIR
from app.state import AUTH, CONFIG, SETUP_COMPLETE_FILE

logger = logging.getLogger("MX-UI")

SESSION_COOKIE = "mxui_session"
SESSION_TTL = 60 * 60 * 24 * 365

# In-memory revocation epoch + HMAC-signed tokens so sessions survive restarts
_SESSION_EPOCH_FILE = DATA_DIR / "session_epoch.txt"
SESSIONS_LOCK = asyncio.Lock()


def _get_epoch() -> str:
    try:
        if _SESSION_EPOCH_FILE.exists():
            val = _SESSION_EPOCH_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
    except Exception:
        pass
    return "1"


def _bump_epoch() -> str:
    new_epoch = str(int(time.time() * 1000))
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _SESSION_EPOCH_FILE.write_text(new_epoch, encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist session epoch: %s", exc)
    return new_epoch


def hash_password(pw: str) -> str:
    return hashlib.sha256(f"{pw}{CONFIG['secret']}".encode()).hexdigest()


def is_default_password_active() -> bool:
    return AUTH["password_hash"] == hash_password("MUVIXO")


def is_setup_complete() -> bool:
    try:
        if SETUP_COMPLETE_FILE.exists():
            return True
        if os.environ.get("ADMIN_PASSWORD") and os.environ.get("ADMIN_PASSWORD") != "MUVIXO":
            return True
        return AUTH["password_hash"] != hash_password("MUVIXO")
    except Exception:
        return False


async def mark_setup_complete() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETUP_COMPLETE_FILE.write_text("setup_complete", encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not mark setup complete: %s", exc)


async def create_session() -> str:
    exp = int(time.time()) + SESSION_TTL
    epoch = _get_epoch()
    payload = f"{exp}.{epoch}"
    sig = hmac.new(CONFIG["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


async def is_valid_session(token: Optional[str]) -> bool:
    if not token or token.count(".") != 2:
        return False
    try:
        exp_str, epoch, sig = token.split(".", 2)
        exp = int(exp_str)
        if exp < int(time.time()):
            return False
        if epoch != _get_epoch():
            return False
        payload = f"{exp_str}.{epoch}"
        expected = hmac.new(CONFIG["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


async def clear_all_sessions() -> None:
    async with SESSIONS_LOCK:
        _bump_epoch()


async def require_auth(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not await is_valid_session(token):
        raise HTTPException(status_code=401, detail="unauthorized")
    return token or ""

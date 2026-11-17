"""Persistent application state, link validation, and formatting helpers."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Optional

import aiofiles

from app.config import DATA_DIR, LOCAL_TZ, PUBLIC_HOST_ENV, PUBLIC_PORT

logger = logging.getLogger("MX-UI")

DATA_FILE = DATA_DIR / "mxui_state.json"
SECRET_FILE = DATA_DIR / "mxui_secret.key"
SETUP_COMPLETE_FILE = DATA_DIR / "setup_complete.lock"
SAVE_LOCK = asyncio.Lock()


def _load_or_create_secret() -> str:
    env_secret = os.environ.get("SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if SECRET_FILE.exists():
            existing = SECRET_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        new_secret = secrets.token_urlsafe(32)
        SECRET_FILE.write_text(new_secret, encoding="utf-8")
        return new_secret
    except Exception as exc:
        logger.warning("Could not persist SECRET_KEY: %s", exc)
        return secrets.token_urlsafe(32)


CONFIG: dict = {
    "port": PUBLIC_PORT,
    "secret": _load_or_create_secret(),
    "host": PUBLIC_HOST_ENV or "localhost",
    "dashboard_path": os.environ.get("DASHBOARD_PATH", "/dashboard"),
    "login_path": os.environ.get("LOGIN_PATH", "/login"),
    "sub_path": os.environ.get("SUB_PATH", "/sub"),
    "setup_path": os.environ.get("SETUP_PATH", "/setup"),
    "cdn_host": os.environ.get("CDN_HOST", "").strip(),
    "ws_path": os.environ.get("WS_PATH", "/ws"),
    "xhttp_path": os.environ.get("XHTTP_PATH", "/xhttp"),
    "panel_location": {
        "country_code": "us",
        "country_name": "United States",
        "city": "Auto",
        "flag_url": "/static/flags/us.svg",
        "auto_detected": True,
    },
}

AUTH: dict = {
    "password_hash": hashlib.sha256(
        f"{os.environ.get('ADMIN_PASSWORD', 'MUVIXO')}{CONFIG['secret']}".encode()
    ).hexdigest()
}

LINKS: dict = {}
LINKS_LOCK = asyncio.Lock()

connections: dict = {}
stats: dict = {
    "total_bytes": 0,
    "total_requests": 0,
    "total_errors": 0,
    "start_time": time.time(),
}
error_logs: deque = deque(maxlen=100)
activity_logs: deque = deque(maxlen=300)
hourly_traffic: dict = defaultdict(int)

PROTOCOLS = (
    "vless-ws",
    "vless-xhttp-packet-up",
    "vless-xhttp-stream-up",
    "trojan-ws",
    "trojan-xhttp-packet-up",
    "trojan-xhttp-stream-up",
)
DEFAULT_PROTOCOL = "vless-ws"

PROTOCOL_ALIASES = {
    "xhttp-packet-up": "vless-xhttp-packet-up",
    "xhttp-stream-up": "vless-xhttp-stream-up",
    "vless-xhttp": "vless-xhttp-packet-up",
    "trojan-xhttp": "trojan-xhttp-packet-up",
}

PROTOCOL_FAMILIES = ("vless", "trojan")
TRANSPORTS = ("ws", "xhttp")
XHTTP_MODES = ("packet-up", "stream-up")

FINGERPRINTS = (
    "chrome",
    "firefox",
    "safari",
    "ios",
    "android",
    "edge",
    "360",
    "qq",
    "random",
    "randomized",
)
DEFAULT_FINGERPRINT = "chrome"
DEFAULT_SPEED_LIMIT = 0


def parse_protocol(proto: str) -> tuple[str, str, str]:
    proto = PROTOCOL_ALIASES.get((proto or DEFAULT_PROTOCOL).lower().strip(), (proto or DEFAULT_PROTOCOL).lower().strip())
    parts = proto.split("-")
    family = parts[0] if parts and parts[0] in PROTOCOL_FAMILIES else "vless"
    transport = parts[1] if len(parts) > 1 and parts[1] in TRANSPORTS else "ws"
    mode = ""
    if transport == "xhttp":
        raw_mode = "-".join(parts[2:]) if len(parts) > 2 else "packet-up"
        mode = raw_mode if raw_mode in XHTTP_MODES else "packet-up"
    return family, transport, mode


def build_protocol(family: str, transport: str, mode: str = "") -> str:
    family = (family or "vless").lower().strip()
    transport = (transport or "ws").lower().strip()
    mode = (mode or "packet-up").lower().strip()
    if family not in PROTOCOL_FAMILIES:
        family = "vless"
    if transport not in TRANSPORTS:
        transport = "ws"
    if transport == "xhttp":
        if mode not in XHTTP_MODES:
            mode = "packet-up"
        return f"{family}-xhttp-{mode}"
    return f"{family}-ws"


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def uptime_str() -> str:
    secs = max(0, int(time.time() - stats["start_time"]))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def generate_uuid() -> str:
    h = secrets.token_hex(16)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def fmt_bytes(b: int) -> str:
    b = max(0, int(b or 0))
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / (1024 ** 2):.2f} MB"
    return f"{b / (1024 ** 3):.2f} GB"


def parse_size_to_bytes(value: float, unit: str) -> int:
    unit = (unit or "MB").upper()
    if unit == "GB":
        return int(value * (1024 ** 3))
    if unit == "MB":
        return int(value * (1024 ** 2))
    if unit == "KB":
        return int(value * 1024)
    return int(value)


def parse_speed_to_bytes(value: float, unit: str) -> int:
    if value <= 0:
        return 0
    unit = (unit or "MBIT").upper()
    if unit == "MBIT":
        return int(value * 1024 * 1024 / 8)
    if unit == "KB":
        return int(value * 1024)
    if unit == "MB":
        return int(value * 1024 * 1024)
    return int(value)


def clean_label(raw: str, fallback: str = "Config") -> str:
    """Preserve Unicode, Persian, English, digits, and safe punctuation."""
    txt = " ".join((raw or "").split()).strip()
    return txt[:80] if txt else fallback


def is_link_expired(link: Optional[dict]) -> bool:
    if not link:
        return False
    exp = link.get("expires_at")
    if not exp:
        return False
    try:
        return datetime.now() > datetime.fromisoformat(exp)
    except Exception:
        return False


def is_link_allowed(link: Optional[dict]) -> bool:
    if link is None:
        return False
    if not link.get("active", True):
        return False
    if is_link_expired(link):
        return False
    lb = int(link.get("limit_bytes", 0) or 0)
    if lb > 0 and int(link.get("used_bytes", 0) or 0) >= lb:
        return False
    return True


def unique_ips_for_uuid(uuid: str) -> set[str]:
    return {
        str(c.get("ip"))
        for c in list(connections.values())
        if c.get("uuid") == uuid and c.get("ip") and c.get("ip") != "unknown"
    }


def is_ip_allowed(link: Optional[dict], uuid: str, ip: str) -> bool:
    if link is None:
        return False
    ip_limit = int(link.get("ip_limit", 0) or 0)
    if ip_limit <= 0 or not ip or ip == "unknown":
        return True
    active_ips = unique_ips_for_uuid(uuid)
    if ip in active_ips:
        return True
    return len(active_ips) < ip_limit


def log_activity(kind: str, message: str, level: str = "info") -> None:
    activity_logs.append(
        {
            "kind": kind,
            "level": level,
            "message": message,
            "time": datetime.now().isoformat(),
        }
    )


async def load_state() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            loaded_links = data.get("links", {})
            async with LINKS_LOCK:
                LINKS.clear()
                LINKS.update(loaded_links)
                for uid, link in LINKS.items():
                    link.setdefault("ip_pool", [])
                    link.setdefault("protocol", DEFAULT_PROTOCOL)
                    link.setdefault("fingerprint", DEFAULT_FINGERPRINT)
                    link.setdefault("alpn", "")
                    link.setdefault("sni", "")
                    link.setdefault("cdn_host", "")
                    link.setdefault("region", "Auto")
                    if link.get("is_default"):
                        link["protocol"] = "all"
            if "password_hash" in data:
                AUTH["password_hash"] = data["password_hash"]
            if "paths" in data:
                for key, value in data["paths"].items():
                    if key in CONFIG and isinstance(value, str) and value.startswith("/"):
                        CONFIG[key] = value
            if "settings" in data and isinstance(data["settings"], dict):
                for key in ("cdn_host", "ws_path", "xhttp_path"):
                    if key in data["settings"] and isinstance(data["settings"][key], str):
                        CONFIG[key] = data["settings"][key]
                if isinstance(data["settings"].get("panel_location"), dict):
                    CONFIG["panel_location"] = data["settings"]["panel_location"]
            if "total_bytes" in data:
                stats["total_bytes"] = int(data.get("total_bytes") or 0)
            logger.info("State loaded: %d links from %s", len(LINKS), DATA_FILE)
    except Exception as exc:
        logger.warning("Could not load state: %s", exc)


async def save_state() -> None:
    async with SAVE_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            async with LINKS_LOCK:
                links_snapshot = dict(LINKS)
            data = {
                "links": links_snapshot,
                "password_hash": AUTH["password_hash"],
                "total_bytes": stats["total_bytes"],
                "saved_at": datetime.now().isoformat(),
                "paths": {
                    "dashboard_path": CONFIG.get("dashboard_path", "/dashboard"),
                    "login_path": CONFIG.get("login_path", "/login"),
                    "sub_path": CONFIG.get("sub_path", "/sub"),
                    "setup_path": CONFIG.get("setup_path", "/setup"),
                },
                "settings": {
                    "cdn_host": CONFIG.get("cdn_host", ""),
                    "ws_path": CONFIG.get("ws_path", "/ws"),
                    "xhttp_path": CONFIG.get("xhttp_path", "/xhttp"),
                    "panel_location": CONFIG.get("panel_location"),
                },
            }
            tmp = DATA_FILE.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            tmp.replace(DATA_FILE)
        except Exception as exc:
            logger.warning("Could not save state: %s", exc)


async def ensure_default_link() -> None:
    async with LINKS_LOCK:
        if any(l.get("is_default") for l in LINKS.values()):
            return
        uid_hex = hashlib.sha256(f"default{CONFIG['secret']}".encode()).hexdigest()
        uid = f"{uid_hex[:8]}-{uid_hex[8:12]}-{uid_hex[12:16]}-{uid_hex[16:20]}-{uid_hex[20:32]}"
        if uid not in LINKS:
            LINKS[uid] = {
                "label": "Default Link",
                "limit_bytes": 0,
                "used_bytes": 0,
                "created_at": datetime.now().isoformat(),
                "active": True,
                "expires_at": None,
                "note": "Protected default inbound configuration",
                "is_default": True,
                "protocol": "all",
                "fingerprint": DEFAULT_FINGERPRINT,
                "alpn": "",
                "sni": "",
                "cdn_host": "",
                "region": "Auto",
                "ip_limit": 0,
                "speed_limit_bytes": DEFAULT_SPEED_LIMIT,
                "last_used": None,
                "ip_pool": [],
            }
    await save_state()

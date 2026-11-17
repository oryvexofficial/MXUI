"""Multi-platform configuration and host/TLS/region detection for MX-UI."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Request

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DEFAULT_TZ = os.environ.get("MXUI_TZ", "Asia/Tehran")
try:
    LOCAL_TZ = ZoneInfo(DEFAULT_TZ)
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")


def resolve_data_dir() -> Path:
    """Resolve a writable persistent data directory across PaaS & VPS."""
    candidates: list[Path] = []
    env_dir = os.environ.get("DATA_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path("/data"))
    candidates.append(BASE_DIR / "data")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue
    return BASE_DIR / "data"


DATA_DIR = resolve_data_dir()

# Port resolution across Railway, Render, Wispbyte (Pterodactyl SERVER_PORT), Lucity, Fly, VPS
PUBLIC_PORT = int(
    os.environ.get("PORT")
    or os.environ.get("SERVER_PORT")
    or os.environ.get("APP_PORT")
    or 8080
)
INTERNAL_PORT = int(os.environ.get("INTERNAL_PORT") or 8001)
if INTERNAL_PORT == PUBLIC_PORT:
    INTERNAL_PORT = PUBLIC_PORT + 1

# Xray internal inbound ports (loopback only)
WS_PORT = int(os.environ.get("XRAY_WS_PORT") or 31801)
XHTTP_PORT = int(os.environ.get("XRAY_XHTTP_PORT") or 31802)
TROJAN_WS_PORT = int(os.environ.get("XRAY_TROJAN_WS_PORT") or 31811)
TROJAN_XHTTP_PORT = int(os.environ.get("XRAY_TROJAN_XHTTP_PORT") or 31812)
API_PORT = int(os.environ.get("XRAY_API_PORT") or 20085)

# TLS mode: "auto" (detect from X-Forwarded-Proto / PaaS), "tls", or "none"
TLS_MODE = os.environ.get("TLS_MODE", "auto").strip().lower()
PUBLIC_CONNECT_PORT_ENV = os.environ.get("PUBLIC_CONNECT_PORT", "").strip()
PUBLIC_HOST_ENV = (
    os.environ.get("PUBLIC_HOST")
    or os.environ.get("PUBLIC_DOMAIN")
    or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    or os.environ.get("KOYEB_PUBLIC_DOMAIN")
    or os.environ.get("LUCITY_DOMAIN")
    or os.environ.get("WISPBYTE_DOMAIN")
    or (f"{os.environ['FLY_APP_NAME']}.fly.dev" if os.environ.get("FLY_APP_NAME") else "")
    or (f"{os.environ['HEROKU_APP_NAME']}.herokuapp.com" if os.environ.get("HEROKU_APP_NAME") else "")
    or os.environ.get("SERVER_IP")
    or ""
).strip()


def detect_platform() -> dict:
    """Detect the hosting platform and return structured capabilities."""
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        return {
            "id": "railway",
            "name": "Railway",
            "paas_tls": True,
            "default_domain_suffixes": ["railway.app", "up.railway.app"],
            "region": os.environ.get("RAILWAY_REPLICA_REGION", os.environ.get("RAILWAY_REGION", "auto")),
        }
    if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        return {
            "id": "render",
            "name": "Render",
            "paas_tls": True,
            "default_domain_suffixes": ["onrender.com"],
            "region": os.environ.get("RENDER_REGION", "auto"),
        }
    if os.environ.get("LUCITY_APP_ID") or os.environ.get("LUCITY_DOMAIN") or os.environ.get("LUCITY_PUBLIC_URL"):
        return {
            "id": "lucity",
            "name": "Lucity",
            "paas_tls": True,
            "default_domain_suffixes": ["lucity.app", "lucity.cloud"],
            "region": os.environ.get("LUCITY_REGION", "auto"),
        }
    if os.environ.get("WISPBYTE_DOMAIN") or os.environ.get("P_SERVER_UUID") or os.environ.get("SERVER_PORT"):
        return {
            "id": "wispbyte",
            "name": "Wispbyte / Container",
            "paas_tls": bool(os.environ.get("WISPBYTE_DOMAIN")),
            "default_domain_suffixes": ["wispbyte.com", "wispbyte.host"],
            "region": os.environ.get("P_SERVER_LOCATION", "auto"),
        }
    if os.environ.get("FLY_APP_NAME"):
        return {
            "id": "fly",
            "name": "Fly.io",
            "paas_tls": True,
            "default_domain_suffixes": ["fly.dev"],
            "region": os.environ.get("FLY_REGION", "auto"),
        }
    if os.environ.get("KOYEB_APP_NAME") or os.environ.get("KOYEB_PUBLIC_DOMAIN"):
        return {
            "id": "koyeb",
            "name": "Koyeb",
            "paas_tls": True,
            "default_domain_suffixes": ["koyeb.app"],
            "region": os.environ.get("KOYEB_REGION", "auto"),
        }
    if os.environ.get("HEROKU_APP_NAME") or os.environ.get("DYNO"):
        return {
            "id": "heroku",
            "name": "Heroku",
            "paas_tls": True,
            "default_domain_suffixes": ["herokuapp.com"],
            "region": "auto",
        }
    if Path("/.dockerenv").exists():
        return {
            "id": "docker",
            "name": "Docker / VPS",
            "paas_tls": False,
            "default_domain_suffixes": [],
            "region": os.environ.get("SERVER_REGION", "custom"),
        }
    return {
        "id": "vps",
        "name": "VPS / Bare Metal",
        "paas_tls": False,
        "default_domain_suffixes": [],
        "region": os.environ.get("SERVER_REGION", "custom"),
    }


PLATFORM_INFO = detect_platform()


def get_scheme(request: Optional[Request] = None) -> str:
    if TLS_MODE == "tls":
        return "https"
    if TLS_MODE == "none":
        return "http"
    if request is not None:
        xf_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if xf_proto in ("http", "https"):
            return xf_proto
        cf_visitor = request.headers.get("cf-visitor", "")
        if '"https"' in cf_visitor:
            return "https"
        if request.url.scheme in ("http", "https"):
            return request.url.scheme
    return "https" if PLATFORM_INFO.get("paas_tls") else "http"


def get_host_and_port(request: Optional[Request] = None) -> tuple[str, int, str]:
    """Return (hostname, connect_port, netloc_for_urls)."""
    scheme = get_scheme(request)
    raw_host = ""
    if request is not None:
        raw_host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or ""
        ).split(",")[0].strip()

    if not raw_host:
        raw_host = PUBLIC_HOST_ENV or "localhost"

    # Strip IPv6 brackets or split host:port safely
    if raw_host.startswith("[") and "]" in raw_host:
        idx = raw_host.index("]")
        hostname = raw_host[: idx + 1]
        port_part = raw_host[idx + 1 :].lstrip(":")
    elif ":" in raw_host:
        hostname, port_part = raw_host.rsplit(":", 1)
    else:
        hostname, port_part = raw_host, ""

    if PUBLIC_CONNECT_PORT_ENV.isdigit():
        connect_port = int(PUBLIC_CONNECT_PORT_ENV)
    elif port_part.isdigit():
        connect_port = int(port_part)
    elif request is not None and request.headers.get("x-forwarded-port", "").isdigit():
        connect_port = int(request.headers["x-forwarded-port"])
    else:
        connect_port = 443 if scheme == "https" else (PUBLIC_PORT if hostname in ("localhost", "127.0.0.1") or not PLATFORM_INFO.get("paas_tls") else 80)

    is_default_port = (scheme == "https" and connect_port == 443) or (scheme == "http" and connect_port == 80)
    netloc = hostname if is_default_port else f"{hostname}:{connect_port}"
    return hostname, connect_port, netloc


def get_host(request: Optional[Request] = None) -> str:
    hostname, _, _ = get_host_and_port(request)
    return hostname


def get_base_url(request: Optional[Request] = None) -> str:
    scheme = get_scheme(request)
    _, _, netloc = get_host_and_port(request)
    return f"{scheme}://{netloc}"


def is_paas_default_domain(host: str) -> bool:
    h = host.lower().strip()
    suffixes = (
        "railway.app",
        "up.railway.app",
        "onrender.com",
        "fly.dev",
        "koyeb.app",
        "herokuapp.com",
        "lucity.app",
        "lucity.cloud",
        "wispbyte.com",
        "wispbyte.host",
    )
    return any(h == s or h.endswith("." + s) for s in suffixes)


def get_client_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    true_client = request.headers.get("true-client-ip")
    if true_client:
        return true_client.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"

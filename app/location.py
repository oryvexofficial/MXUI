"""Panel location detection and country flag resolution."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from app.config import STATIC_DIR

logger = logging.getLogger("MX-UI")

FLAGS_DIR = STATIC_DIR / "flags"
COUNTRIES_FILE = FLAGS_DIR / "countries.json"

_COUNTRIES_CACHE: list[dict] | None = None
_COUNTRY_MAP: dict[str, str] | None = None

REGION_HINTS: dict[str, tuple[str, str]] = {
    "us-east": ("us", "Virginia"),
    "us-west": ("us", "Oregon"),
    "iad": ("us", "Ashburn"),
    "ord": ("us", "Chicago"),
    "sjc": ("us", "San Jose"),
    "lax": ("us", "Los Angeles"),
    "ewr": ("us", "Newark"),
    "dfw": ("us", "Dallas"),
    "sea": ("us", "Seattle"),
    "mia": ("us", "Miami"),
    "oregon": ("us", "Oregon"),
    "ohio": ("us", "Ohio"),
    "virginia": ("us", "Virginia"),
    "eu-west": ("nl", "Amsterdam"),
    "eu-central": ("de", "Frankfurt"),
    "fra": ("de", "Frankfurt"),
    "frankfurt": ("de", "Frankfurt"),
    "ams": ("nl", "Amsterdam"),
    "amsterdam": ("nl", "Amsterdam"),
    "lhr": ("gb", "London"),
    "london": ("gb", "London"),
    "cdg": ("fr", "Paris"),
    "paris": ("fr", "Paris"),
    "arn": ("se", "Stockholm"),
    "mad": ("es", "Madrid"),
    "waw": ("pl", "Warsaw"),
    "sin": ("sg", "Singapore"),
    "singapore": ("sg", "Singapore"),
    "asia-southeast": ("sg", "Singapore"),
    "nrt": ("jp", "Tokyo"),
    "hnd": ("jp", "Tokyo"),
    "tokyo": ("jp", "Tokyo"),
    "hkg": ("hk", "Hong Kong"),
    "icn": ("kr", "Seoul"),
    "syd": ("au", "Sydney"),
    "yyz": ("ca", "Toronto"),
    "gru": ("br", "Sao Paulo"),
    "dxb": ("ae", "Dubai"),
    "ist": ("tr", "Istanbul"),
    "thr": ("ir", "Tehran"),
}


def load_countries() -> list[dict]:
    global _COUNTRIES_CACHE, _COUNTRY_MAP
    if _COUNTRIES_CACHE is not None:
        return _COUNTRIES_CACHE
    try:
        items = json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))
        _COUNTRIES_CACHE = [
            {
                "code": item["code"].lower(),
                "name": item["name"],
                "flag_url": f"/static/flags/{item['code'].lower()}.svg",
            }
            for item in items
        ]
        _COUNTRY_MAP = {c["code"]: c["name"] for c in _COUNTRIES_CACHE}
    except Exception as exc:
        logger.warning("Could not load countries.json: %s", exc)
        _COUNTRIES_CACHE = [{"code": "us", "name": "United States", "flag_url": "/static/flags/us.svg"}]
        _COUNTRY_MAP = {"us": "United States"}
    return _COUNTRIES_CACHE


def get_country_name(code: str) -> str:
    load_countries()
    cc = (code or "un").lower().strip()
    if _COUNTRY_MAP and cc in _COUNTRY_MAP:
        return _COUNTRY_MAP[cc]
    return "Global" if cc == "un" else cc.upper()


def flag_url_for(code: str) -> str:
    cc = (code or "un").lower().strip()
    if (FLAGS_DIR / f"{cc}.svg").exists():
        return f"/static/flags/{cc}.svg"
    return "/static/flags/un.svg"


def build_location(country_code: str, city: str = "", auto_detected: bool = False) -> dict:
    cc = (country_code or "un").lower().strip()
    if len(cc) != 2 or not cc.isalpha():
        cc = "un"
    name = get_country_name(cc)
    return {
        "country_code": cc,
        "country_name": name,
        "city": (city or "").strip(),
        "flag_url": flag_url_for(cc),
        "auto_detected": auto_detected,
    }


def detect_location_from_env() -> Optional[dict]:
    explicit_cc = (os.environ.get("PANEL_COUNTRY") or os.environ.get("SERVER_COUNTRY") or "").strip().lower()
    explicit_city = (os.environ.get("PANEL_CITY") or os.environ.get("SERVER_CITY") or "").strip()
    if explicit_cc:
        return build_location(explicit_cc, explicit_city, auto_detected=False)

    for env_key in (
        "RAILWAY_REPLICA_REGION",
        "RAILWAY_REGION",
        "RENDER_REGION",
        "FLY_REGION",
        "KOYEB_REGION",
        "LUCITY_REGION",
        "P_SERVER_LOCATION",
        "SERVER_REGION",
    ):
        raw = os.environ.get(env_key, "").strip().lower()
        if not raw or raw == "auto":
            continue
        for hint, (cc, city) in REGION_HINTS.items():
            if hint in raw:
                return build_location(cc, explicit_city or city, auto_detected=True)
    return None


async def auto_detect_location() -> dict:
    env_loc = detect_location_from_env()
    if env_loc:
        return env_loc

    # Try fast non-blocking IP geolocation when running on a connected server
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("https://ipwho.is/")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("country_code"):
                    return build_location(
                        data["country_code"],
                        data.get("city", ""),
                        auto_detected=True,
                    )
    except Exception:
        pass

    return build_location("us", "Auto", auto_detected=True)

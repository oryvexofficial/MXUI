"""Curated edge/CDN IP suggestion loader with caching."""
from __future__ import annotations

import random

from app.config import BASE_DIR, DATA_DIR

_CACHED_IPS: list[str] | None = None


def _resolve_ips_file():
    for path in (DATA_DIR / "ips.txt", BASE_DIR / "data" / "ips.txt", BASE_DIR / "ips.txt"):
        if path.exists():
            return path
    return None


def load_ips() -> list[str]:
    global _CACHED_IPS
    if _CACHED_IPS is not None:
        return _CACHED_IPS
    ips_file = _resolve_ips_file()
    if not ips_file:
        _CACHED_IPS = []
        return _CACHED_IPS
    with open(ips_file, "r", encoding="utf-8") as f:
        _CACHED_IPS = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return _CACHED_IPS


def get_random_ips(count: int = 12) -> list[str]:
    all_ips = load_ips()
    if not all_ips:
        return []
    if len(all_ips) <= count:
        return list(all_ips)
    return random.sample(all_ips, count)

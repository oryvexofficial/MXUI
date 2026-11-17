"""Configuration CRUD, QR generation, and concurrent cross-region node health testing."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import socket
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app import xray_manager
from app.auth import require_auth
from app.config import PUBLIC_PORT, get_base_url, get_host_and_port, get_scheme
from app.links import primary_link_for_config
from app.qr_generator import generate_qr_base64
from app.state import (
    CONFIG,
    DEFAULT_FINGERPRINT,
    DEFAULT_PROTOCOL,
    LINKS,
    LINKS_LOCK,
    PROTOCOLS,
    clean_label,
    generate_uuid,
    is_link_allowed,
    is_link_expired,
    log_activity,
    parse_size_to_bytes,
    parse_speed_to_bytes,
    save_state,
    unique_ips_for_uuid,
)

router = APIRouter(prefix="/api", tags=["links"])


@router.get("/links")
async def list_links(request: Request, _=Depends(require_auth)):
    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    base_url = get_base_url(request)
    sub_prefix = CONFIG.get("sub_path", "/sub").rstrip("/")

    async with LINKS_LOCK:
        snap = dict(LINKS)

    result = []
    for uid, d in snap.items():
        result.append(
            {
                "uuid": uid,
                **d,
                "expired": is_link_expired(d),
                "vless_link": primary_link_for_config(d, uid, host, connect_port, scheme),
                "sub_url": f"{base_url}{sub_prefix}/{uid}",
                "info_url": f"{base_url}{sub_prefix}/{uid}/info",
                "portal_url": f"{base_url}{sub_prefix}/user?uuid={uid}",
                "connected_ips": len(unique_ips_for_uuid(uid)),
                "is_default": d.get("is_default", False),
                "applied_ips_count": len(d.get("ip_pool") or []),
            }
        )
    result.sort(key=lambda x: (not x.get("is_default", False), x.get("created_at", "")), reverse=True)
    return {"links": result}


@router.post("/links")
async def create_link(request: Request, _=Depends(require_auth)):
    body = await request.json()
    lv = float(body.get("limit_value") or 0)
    lu = body.get("limit_unit") or "MB"
    limit_bytes = 0 if lv <= 0 else parse_size_to_bytes(lv, lu)
    exp_days = int(body.get("expires_days") or 0)
    expires_at = (datetime.now() + timedelta(days=exp_days)).isoformat() if exp_days > 0 else None
    try:
        ip_limit = max(0, int(body.get("ip_limit") or 0))
    except Exception:
        ip_limit = 0

    sv = float(body.get("speed_limit_value") or 0)
    su = body.get("speed_limit_unit") or "MBIT"
    speed_limit_bytes = 0 if sv <= 0 else parse_speed_to_bytes(sv, su)

    protocol = body.get("protocol") or DEFAULT_PROTOCOL
    if protocol not in PROTOCOLS:
        protocol = DEFAULT_PROTOCOL
    fp = body.get("fingerprint") or DEFAULT_FINGERPRINT
    uid = generate_uuid()
    label = clean_label(body.get("label") or "Config", "Config")

    entry = {
        "label": label,
        "limit_bytes": max(0, limit_bytes),
        "used_bytes": 0,
        "created_at": datetime.now().isoformat(),
        "active": True,
        "expires_at": expires_at,
        "note": (body.get("note") or "").strip()[:200],
        "is_default": False,
        "protocol": protocol,
        "fingerprint": fp,
        "alpn": (body.get("alpn") or "").strip()[:100],
        "sni": (body.get("sni") or "").strip()[:120],
        "cdn_host": (body.get("cdn_host") or "").strip()[:120],
        "region": (body.get("region") or "Auto").strip()[:40],
        "ip_limit": ip_limit,
        "speed_limit_bytes": max(0, speed_limit_bytes),
        "last_used": None,
        "ip_pool": [],
    }
    async with LINKS_LOCK:
        LINKS[uid] = entry

    await save_state()
    asyncio.create_task(xray_manager.reload_config())
    log_activity("config", f"Created config '{label}' ({protocol})", "ok")

    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    base_url = get_base_url(request)
    sub_prefix = CONFIG.get("sub_path", "/sub").rstrip("/")
    return {
        "uuid": uid,
        **entry,
        "expired": False,
        "vless_link": primary_link_for_config(entry, uid, host, connect_port, scheme),
        "sub_url": f"{base_url}{sub_prefix}/{uid}",
        "info_url": f"{base_url}{sub_prefix}/{uid}/info",
    }


@router.patch("/links/{uid}")
async def update_link(uid: str, request: Request, _=Depends(require_auth)):
    body = await request.json()
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(status_code=404, detail="link not found")
        link = LINKS[uid]
        if link.get("is_default", False):
            raise HTTPException(status_code=403, detail="Default configuration cannot be modified")
        if "active" in body:
            link["active"] = bool(body["active"])
        if "label" in body:
            link["label"] = clean_label(str(body["label"]), link["label"])
        if "protocol" in body and body["protocol"] in PROTOCOLS:
            link["protocol"] = str(body["protocol"])
        if "fingerprint" in body:
            link["fingerprint"] = str(body["fingerprint"])
        if "alpn" in body:
            link["alpn"] = str(body["alpn"]).strip()[:100]
        if "sni" in body:
            link["sni"] = str(body["sni"]).strip()[:120]
        if "cdn_host" in body:
            link["cdn_host"] = str(body["cdn_host"]).strip()[:120]
        if "region" in body:
            link["region"] = str(body["region"]).strip()[:40] or "Auto"
        if "note" in body:
            link["note"] = str(body["note"]).strip()[:200]
        if "ip_limit" in body:
            try:
                link["ip_limit"] = max(0, int(body["ip_limit"] or 0))
            except Exception:
                pass
        if "limit_value" in body:
            lv = float(body.get("limit_value") or 0)
            lu = body.get("limit_unit") or "MB"
            link["limit_bytes"] = 0 if lv <= 0 else parse_size_to_bytes(lv, lu)
        if "expires_days" in body:
            ed = int(body.get("expires_days") or 0)
            if ed > 0:
                link["expires_at"] = (datetime.now() + timedelta(days=ed)).isoformat()
            elif ed == 0 and body.get("clear_expiry"):
                link["expires_at"] = None
        if "speed_limit_value" in body:
            sv = float(body.get("speed_limit_value") or 0)
            su = body.get("speed_limit_unit") or "MBIT"
            link["speed_limit_bytes"] = 0 if sv <= 0 else parse_speed_to_bytes(sv, su)

    await save_state()
    asyncio.create_task(xray_manager.reload_config())
    log_activity("config", f"Updated config '{LINKS[uid]['label']}'", "info")
    return {"ok": True}


@router.delete("/links/{uid}")
async def delete_link(uid: str, _=Depends(require_auth)):
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(status_code=404, detail="link not found")
        if LINKS[uid].get("is_default", False):
            raise HTTPException(status_code=403, detail="Default configuration cannot be deleted")
        label = LINKS[uid].get("label", uid[:8])
        del LINKS[uid]
    await save_state()
    asyncio.create_task(xray_manager.reload_config())
    log_activity("config", f"Deleted config '{label}'", "warn")
    return {"ok": True}


@router.patch("/links/{uid}/toggle")
async def toggle_link(uid: str, request: Request, _=Depends(require_auth)):
    body = await request.json()
    active = bool(body.get("active", True))
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(status_code=404, detail="link not found")
        LINKS[uid]["active"] = active
        label = LINKS[uid].get("label", uid[:8])
    await save_state()
    asyncio.create_task(xray_manager.reload_config())
    log_activity("config", f"{'Enabled' if active else 'Disabled'} config '{label}'", "info")
    return {"ok": True, "active": active}


@router.post("/links/{uid}/reset-traffic")
async def reset_traffic(uid: str, _=Depends(require_auth)):
    async with LINKS_LOCK:
        if uid not in LINKS:
            raise HTTPException(status_code=404, detail="link not found")
        LINKS[uid]["used_bytes"] = 0
        LINKS[uid]["active"] = True
        label = LINKS[uid].get("label", uid[:8])
    await save_state()
    asyncio.create_task(xray_manager.reload_config())
    log_activity("config", f"Reset traffic for '{label}'", "info")
    return {"ok": True}


@router.get("/qr")
async def get_qr(request: Request):
    data = request.query_params.get("data", "")
    if not data:
        raise HTTPException(status_code=400, detail="Missing data")
    return {"qr": generate_qr_base64(data, size=300)}


@router.get("/qr/{uid}")
async def get_qr_for_uid(uid: str, request: Request, _=Depends(require_auth)):
    async with LINKS_LOCK:
        link = LINKS.get(uid)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    uri = primary_link_for_config(link, uid, host, connect_port, scheme)
    return {"qr": generate_qr_base64(uri, size=300), "link": uri}


def _tcp_probe(host: str, port: int, timeout: float = 2.0) -> float | None:
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            return round((time.monotonic() - t0) * 1000.0, 1)
    except Exception:
        return None


@router.post("/configs/test")
async def test_configs(request: Request, _=Depends(require_auth)):
    body = await request.json()
    uuids = body.get("uuids", [])
    if not uuids:
        raise HTTPException(status_code=400, detail="No UUIDs provided")

    host, connect_port, _ = get_host_and_port(request)
    async with LINKS_LOCK:
        snap = {uid: dict(LINKS.get(uid) or {}) for uid in uuids}

    loop = asyncio.get_running_loop()

    async def probe_one(uid: str) -> tuple[str, dict]:
        link = snap.get(uid)
        if not link:
            return uid, {"healthy": False, "latency": None, "error": "Not found", "endpoint": "-", "xray_ok": False}

        if not is_link_allowed(link):
            reason = "Expired" if is_link_expired(link) else ("Quota exceeded" if link.get("active", True) else "Disabled")
            return uid, {"healthy": False, "latency": None, "error": reason, "endpoint": "-", "xray_ok": False}

        proto = link.get("protocol", DEFAULT_PROTOCOL)
        inbound_port = xray_manager.inbound_port_for_protocol(proto, bool(link.get("is_default")))
        xray_ms = await loop.run_in_executor(None, _tcp_probe, "127.0.0.1", inbound_port, 1.5)
        if xray_ms is None:
            return uid, {
                "healthy": False,
                "latency": None,
                "error": f"Xray inbound offline (:{inbound_port})",
                "endpoint": f"127.0.0.1:{inbound_port}",
                "xray_ok": False,
            }

        targets: list[tuple[str, int, str]] = []
        for entry in link.get("ip_pool") or []:
            ip = entry.get("ip")
            port = int(entry.get("port") or connect_port or 443)
            if ip:
                targets.append((ip, port, f"{ip}:{port}"))
        cdn = (link.get("cdn_host") or CONFIG.get("cdn_host") or "").strip()
        if cdn:
            targets.append((cdn, connect_port, f"{cdn}:{connect_port}"))
        if host and host not in ("localhost", "127.0.0.1"):
            targets.append((host, connect_port, f"{host}:{connect_port}"))

        for thost, tport, label in targets:
            ms = await loop.run_in_executor(None, _tcp_probe, thost, tport, 2.0)
            if ms is not None:
                return uid, {"healthy": True, "latency": ms, "error": None, "endpoint": label, "xray_ok": True}

        # Fallback for NAT/Pterodactyl containers (e.g. Wispbyte) where hairpin NAT blocks probing own public IP
        local_port = CONFIG.get("port") or PUBLIC_PORT
        local_ms = await loop.run_in_executor(None, _tcp_probe, "127.0.0.1", int(local_port), 1.5)
        if local_ms is not None:
            return uid, {
                "healthy": True,
                "latency": local_ms,
                "error": None,
                "endpoint": f"127.0.0.1:{local_port} (local)",
                "xray_ok": True,
            }

        ep = targets[0][2] if targets else f"127.0.0.1:{local_port}"
        return uid, {
            "healthy": False,
            "latency": None,
            "error": "Unreachable",
            "endpoint": ep,
            "xray_ok": True,
        }

    pairs = await asyncio.gather(*(probe_one(uid) for uid in uuids))
    return {"results": dict(pairs)}

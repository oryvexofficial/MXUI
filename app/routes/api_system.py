"""System diagnostics, health checks, connections, activity, platform info, and DB export/import."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app import xray_manager
from app.auth import require_auth
from app.config import (
    DATA_DIR,
    PLATFORM_INFO,
    TLS_MODE,
    get_host_and_port,
    get_scheme,
    is_paas_default_domain,
)
from app.ip_suggest import get_random_ips
from app.location import build_location, load_countries
from app.state import (
    CONFIG,
    LINKS,
    LINKS_LOCK,
    activity_logs,
    connections,
    error_logs,
    hourly_traffic,
    is_link_allowed,
    is_link_expired,
    log_activity,
    save_state,
    stats,
    uptime_str,
)
from app.system_stats import collect_system_stats

router = APIRouter(tags=["system"])


@router.get("/healthz")
@router.get("/health")
async def healthz():
    st = xray_manager.port_status()
    return {
        "ok": True,
        "service": "mx-ui",
        "platform": PLATFORM_INFO["id"],
        "xray_running": bool(st.get("xray_running")),
        "uptime": uptime_str(),
    }


@router.get("/readyz")
async def readyz():
    st = xray_manager.port_status()
    if st.get("xray_running"):
        return {"ready": True, "platform": PLATFORM_INFO["id"]}
    raise HTTPException(status_code=503, detail="xray not ready")


@router.get("/stats")
async def get_stats(_=Depends(require_auth)):
    async with LINKS_LOCK:
        snap = dict(LINKS)

    sys_metrics = collect_system_stats()
    xray_st = xray_manager.port_status()

    return {
        "active_connections": len(connections),
        "total_traffic_mb": round(stats["total_bytes"] / (1024 ** 2), 2),
        "total_requests": stats["total_requests"],
        "total_errors": stats["total_errors"],
        "uptime": uptime_str(),
        "timestamp": datetime.now().isoformat(),
        "hourly": dict(hourly_traffic),
        "recent_errors": list(error_logs)[-10:],
        "links_count": len(snap),
        "active_links": sum(1 for l in snap.values() if is_link_allowed(l)),
        "expired_links": sum(1 for l in snap.values() if is_link_expired(l)),
        "xray_running": xray_st.get("xray_running", False),
        "xray_version": xray_st.get("xray_version", "unknown"),
        "platform": PLATFORM_INFO,
        "panel_location": CONFIG.get("panel_location"),
        **sys_metrics,
    }


@router.get("/api/connections")
async def get_connections(_=Depends(require_auth)):
    items = [
        {"id": cid, **data}
        for cid, data in list(connections.items())
    ]
    return {"connections": items, "count": len(items)}


@router.get("/api/activity")
async def get_activity(_=Depends(require_auth)):
    return {"logs": list(activity_logs)[-100:][::-1]}


@router.get("/api/platform")
async def get_platform(request: Request, _=Depends(require_auth)):
    host, connect_port, netloc = get_host_and_port(request)
    scheme = get_scheme(request)
    xray_st = xray_manager.port_status()
    return {
        "platform": PLATFORM_INFO,
        "host": host,
        "connect_port": connect_port,
        "scheme": scheme,
        "tls_mode": TLS_MODE,
        "netloc": netloc,
        "data_dir": str(DATA_DIR),
        "cdn_host": CONFIG.get("cdn_host", ""),
        "panel_location": CONFIG.get("panel_location"),
        "xray": xray_st,
    }


@router.get("/api/domain/check")
async def check_domain(request: Request, _=Depends(require_auth)):
    host, connect_port, _ = get_host_and_port(request)
    is_paas = is_paas_default_domain(host)
    return {
        "host": host,
        "port": connect_port,
        "is_railway": "railway.app" in host.lower(),
        "is_paas_default": is_paas,
        "platform": PLATFORM_INFO["name"],
    }


@router.get("/api/ips/suggest")
async def suggest_ips(_=Depends(require_auth)):
    ips = get_random_ips(12)
    return {"ips": ips, "count": len(ips)}


@router.post("/api/ips/apply")
async def apply_ips(request: Request, _=Depends(require_auth)):
    body = await request.json()
    new_ips = [str(ip).strip() for ip in (body.get("ips") or []) if str(ip).strip()]
    target_uuids = body.get("target_uuids") or []
    _, connect_port, _ = get_host_and_port(request)
    port = int(body.get("port") or connect_port or 443)

    async with LINKS_LOCK:
        for uid in target_uuids:
            if uid in LINKS:
                LINKS[uid]["ip_pool"] = [{"ip": ip, "port": port} for ip in new_ips]
    await save_state()
    log_activity("network", f"Applied {len(new_ips)} edge IP(s) to {len(target_uuids)} config(s)", "ok")
    return {"ok": True}


@router.get("/api/countries")
async def get_countries(_=Depends(require_auth)):
    return {"countries": load_countries()}


@router.get("/api/settings")
async def get_settings(_=Depends(require_auth)):
    return {
        "cdn_host": CONFIG.get("cdn_host", ""),
        "panel_location": CONFIG.get("panel_location"),
        "dashboard_path": CONFIG.get("dashboard_path", "/dashboard"),
        "login_path": CONFIG.get("login_path", "/login"),
        "sub_path": CONFIG.get("sub_path", "/sub"),
    }


@router.post("/api/settings")
async def update_settings(request: Request, _=Depends(require_auth)):
    body = await request.json()
    if "cdn_host" in body:
        CONFIG["cdn_host"] = str(body["cdn_host"] or "").strip()[:120]

    await save_state()
    log_activity("settings", "Updated panel location & network settings", "info")
    return {"ok": True, "cdn_host": CONFIG["cdn_host"], "panel_location": CONFIG.get("panel_location")}


@router.get("/api/database/export")
async def export_db(_=Depends(require_auth)):
    async with LINKS_LOCK:
        return {"links": dict(LINKS), "exported_at": datetime.now().isoformat(), "version": "1.0.0"}


@router.post("/api/database/import")
async def import_db(request: Request, _=Depends(require_auth)):
    body = await request.json()
    incoming = body.get("links")
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="Invalid database JSON: missing 'links' object")
    imported = 0
    async with LINKS_LOCK:
        for uid, data in incoming.items():
            if isinstance(data, dict) and uid not in LINKS:
                LINKS[uid] = data
                imported += 1
    await save_state()
    await xray_manager.reload_config()
    log_activity("database", f"Imported {imported} configuration(s) from backup", "ok")
    return {"ok": True, "imported": imported}

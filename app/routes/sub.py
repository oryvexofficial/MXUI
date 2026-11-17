"""Subscription endpoints: portal page, info page, and standard Base64/Userinfo feeds."""
from __future__ import annotations

import base64
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import TEMPLATES_DIR, get_base_url, get_host_and_port, get_scheme
from app.links import build_all_proxy_links, primary_link_for_config
from app.qr_generator import generate_qr_base64
from app.state import (
    CONFIG,
    LINKS,
    LINKS_LOCK,
    fmt_bytes,
    is_link_allowed,
    save_state,
    unique_ips_for_uuid,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["subscriptions"])


def _subscription_userinfo_header(link: dict) -> str:
    used = int(link.get("used_bytes", 0) or 0)
    limit = int(link.get("limit_bytes", 0) or 0)
    expire_ts = 0
    if link.get("expires_at"):
        try:
            expire_ts = int(datetime.fromisoformat(link["expires_at"]).timestamp())
        except Exception:
            expire_ts = 0
    return f"upload=0; download={used}; total={limit}; expire={expire_ts}"


async def render_sub_user(request: Request, uuid: str):
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        raise HTTPException(status_code=404, detail="Subscription not found")

    used = int(link.get("used_bytes", 0) or 0)
    limit = int(link.get("limit_bytes", 0) or 0)
    if limit > 0 and used >= limit and link.get("active", True):
        async with LINKS_LOCK:
            LINKS[uuid]["active"] = False
            link = LINKS[uuid]
        await save_state()

    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    base_url = get_base_url(request)
    sub_prefix = CONFIG.get("sub_path", "/sub").rstrip("/")

    primary_uri = primary_link_for_config(link, uuid, host, connect_port, scheme)
    all_links = build_all_proxy_links(link, uuid, host, connect_port, scheme)
    active = is_link_allowed(link)
    ips = sorted(unique_ips_for_uuid(uuid))

    quota_str = "Unlimited" if limit == 0 else fmt_bytes(limit)
    remained = "Unlimited" if limit == 0 else fmt_bytes(max(0, limit - used))
    usage_pct = 0.0 if limit == 0 else round(min(100.0, (used / limit) * 100.0), 1)

    def _tag_from_uri(uri: str, idx: int) -> str:
        if "#" in uri:
            from urllib.parse import unquote
            rem = unquote(uri.split("#", 1)[1])
            if "(" in rem and rem.endswith(")"):
                return rem.rsplit("(", 1)[1][:-1]
        return "Primary" if idx == 0 else f"Edge {idx}"

    link_items = [
        {"tag": _tag_from_uri(uri, i), "is_primary": i == 0, "uri": uri}
        for i, uri in enumerate(all_links)
    ]

    return templates.TemplateResponse(
        "sub_user.html",
        {
            "request": request,
            "label": link.get("label", "Config"),
            "uuid": uuid,
            "protocol": link.get("protocol", "vless-ws"),
            "region": link.get("region", "Auto"),
            "active": active,
            "qr_url": generate_qr_base64(primary_uri, size=300),
            "used_fmt": fmt_bytes(used),
            "limit_fmt": quota_str,
            "remained": remained,
            "usage_pct": usage_pct,
            "last_online": link.get("last_used") or "Never",
            "expiry": (link.get("expires_at") or "No expiry")[:10] if link.get("expires_at") else "No expiry",
            "ips_display": ", ".join(ips) if ips else "No active connections",
            "ips_count": len(ips),
            "applied_ips_count": len(link.get("ip_pool") or []),
            "vless_link": primary_uri,
            "sub_url": f"{base_url}{sub_prefix}/{uuid}",
            "link_items": link_items,
        },
    )


async def render_sub_info(request: Request, uuid: str):
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link:
        raise HTTPException(status_code=404, detail="Subscription not found")

    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    base_url = get_base_url(request)
    sub_prefix = CONFIG.get("sub_path", "/sub").rstrip("/")

    used = int(link.get("used_bytes", 0) or 0)
    limit = int(link.get("limit_bytes", 0) or 0)

    return templates.TemplateResponse(
        "sub_info.html",
        {
            "request": request,
            "label": link.get("label", "Config"),
            "active": is_link_allowed(link),
            "used_fmt": fmt_bytes(used),
            "limit_fmt": "Unlimited" if limit == 0 else fmt_bytes(limit),
            "expires_at": (link.get("expires_at") or "Never")[:10] if link.get("expires_at") else "Never",
            "vless_link": primary_link_for_config(link, uuid, host, connect_port, scheme),
            "sub_url": f"{base_url}{sub_prefix}/{uuid}",
            "portal_url": f"{base_url}{sub_prefix}/user?uuid={uuid}",
        },
    )


async def subscription_single_feed(uuid: str, request: Request) -> Response:
    async with LINKS_LOCK:
        link = LINKS.get(uuid)
    if not link or not is_link_allowed(link):
        raise HTTPException(status_code=404, detail="not found or inactive")

    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    all_links = build_all_proxy_links(link, uuid, host, connect_port, scheme)
    content = base64.b64encode("\n".join(all_links).encode()).decode()
    headers = {
        "Subscription-Userinfo": _subscription_userinfo_header(link),
        "Profile-Update-Interval": "12",
        "Profile-Title": link.get("label", "MX-UI"),
    }
    return Response(content=content, media_type="text/plain", headers=headers)


@router.get("/sub/user")
async def sub_user_route(request: Request, uuid: str = Query(...)):
    return await render_sub_user(request, uuid)


@router.get("/sub/{uuid}/info")
async def sub_info_route(uuid: str, request: Request):
    return await render_sub_info(request, uuid)


@router.get("/sub/{uuid}")
async def sub_single_route(uuid: str, request: Request):
    return await subscription_single_feed(uuid, request)


@router.get("/sub-all")
async def sub_all_route(request: Request, _=Depends(require_auth)):
    host, connect_port, _ = get_host_and_port(request)
    scheme = get_scheme(request)
    async with LINKS_LOCK:
        lines: list[str] = []
        for uid, d in LINKS.items():
            if is_link_allowed(d):
                lines.extend(build_all_proxy_links(d, uid, host, connect_port, scheme))
    content = base64.b64encode("\n".join(lines).encode()).decode()
    return Response(content=content, media_type="text/plain")

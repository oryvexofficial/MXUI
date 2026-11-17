"""HTML page routes and dynamic custom-path catch-all."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import SESSION_COOKIE, is_setup_complete, is_valid_session
from app.config import PLATFORM_INFO, TEMPLATES_DIR
from app.routes.sub import render_sub_info, render_sub_user, subscription_single_feed
from app.state import CONFIG, ensure_default_link

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["pages"])


async def render_dashboard(request: Request):
    if not is_setup_complete():
        return RedirectResponse(url=CONFIG.get("setup_path", "/setup"), status_code=302)
    token = request.cookies.get(SESSION_COOKIE)
    if not await is_valid_session(token):
        return RedirectResponse(url=CONFIG.get("login_path", "/login"), status_code=302)
    await ensure_default_link()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "platform_name": PLATFORM_INFO["name"],
            "platform_id": PLATFORM_INFO["id"],
            "panel_location": CONFIG.get("panel_location", {}),
        },
    )


async def render_login(request: Request):
    if not is_setup_complete():
        return RedirectResponse(url=CONFIG.get("setup_path", "/setup"), status_code=302)
    if await is_valid_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url=CONFIG.get("dashboard_path", "/dashboard"), status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "dashboard_path": CONFIG.get("dashboard_path", "/dashboard")},
    )


async def render_setup(request: Request):
    if is_setup_complete():
        return RedirectResponse(url=CONFIG.get("login_path", "/login"), status_code=302)
    return templates.TemplateResponse(
        "setup.html",
        {"request": request, "login_path": CONFIG.get("login_path", "/login")},
    )


@router.get("/")
async def root(request: Request):
    dashboard_path = CONFIG.get("dashboard_path", "/dashboard")
    if dashboard_path == "/":
        return await render_dashboard(request)
    return RedirectResponse(url=dashboard_path, status_code=302)


@router.get("/dashboard")
async def dashboard_default(request: Request):
    dashboard_path = CONFIG.get("dashboard_path", "/dashboard")
    if dashboard_path != "/dashboard":
        return RedirectResponse(url=dashboard_path, status_code=302)
    return await render_dashboard(request)


@router.get("/login")
async def login_default(request: Request):
    login_path = CONFIG.get("login_path", "/login")
    if login_path != "/login":
        return RedirectResponse(url=login_path, status_code=302)
    return await render_login(request)


@router.get("/setup")
async def setup_default(request: Request):
    setup_path = CONFIG.get("setup_path", "/setup")
    if setup_path != "/setup":
        return RedirectResponse(url=setup_path, status_code=302)
    return await render_setup(request)


@router.get("/{path:path}")
async def dynamic_catchall(request: Request, path: str):
    if path in ("ws", "ws-trojan") or path.startswith(("ws/", "xhttp", "static/")):
        return Response(status_code=404)
    if path.startswith(("api/", "stats", "health", "readyz")):
        raise HTTPException(status_code=404, detail="Not Found")

    dashboard_path = CONFIG.get("dashboard_path", "/dashboard").lstrip("/")
    login_path = CONFIG.get("login_path", "/login").lstrip("/")
    setup_path = CONFIG.get("setup_path", "/setup").lstrip("/")
    sub_path = CONFIG.get("sub_path", "/sub").lstrip("/")

    if path == dashboard_path or path == "dashboard":
        return await render_dashboard(request)
    if path == login_path or path == "login":
        return await render_login(request)
    if path == setup_path or path == "setup":
        return await render_setup(request)
    if path.startswith(sub_path + "/"):
        rest = path[len(sub_path) + 1 :].strip("/")
        if rest == "user":
            uid = request.query_params.get("uuid", "")
            if not uid:
                raise HTTPException(status_code=400, detail="Missing uuid")
            return await render_sub_user(request, uid)
        if rest.endswith("/info"):
            return await render_sub_info(request, rest[:-5].strip("/"))
        if rest:
            return await subscription_single_feed(rest, request)
    return RedirectResponse(url=f"/{dashboard_path}", status_code=302)

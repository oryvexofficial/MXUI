"""Authentication and path configuration API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    clear_all_sessions,
    create_session,
    hash_password,
    is_default_password_active,
    is_setup_complete,
    is_valid_session,
    mark_setup_complete,
    require_auth,
)
from app.config import get_scheme
from app.state import AUTH, CONFIG, log_activity, save_state

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/setup")
async def setup_admin(request: Request):
    if is_setup_complete():
        raise HTTPException(status_code=403, detail="Setup already completed")
    body = await request.json()
    password = str(body.get("password", ""))
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    AUTH["password_hash"] = hash_password(password)
    await mark_setup_complete()
    await clear_all_sessions()
    await save_state()
    log_activity("auth", "Initial admin password configured", "ok")
    return {"ok": True, "message": "Password set successfully"}


@router.post("/login")
async def api_login(request: Request):
    if not is_setup_complete():
        raise HTTPException(status_code=403, detail="Setup required. Please visit /setup")
    body = await request.json()
    if hash_password(str(body.get("password", ""))) != AUTH["password_hash"]:
        log_activity("auth", "Failed login attempt", "warn")
        raise HTTPException(status_code=401, detail="Wrong password")
    token = await create_session()
    resp = JSONResponse({"ok": True, "dashboard_path": CONFIG.get("dashboard_path", "/dashboard")})
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=(request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https" or request.url.scheme == "https"),
        path="/",
    )
    log_activity("auth", "Admin signed in", "ok")
    return resp


@router.post("/logout")
async def api_logout(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
async def api_me(request: Request):
    return {"authenticated": await is_valid_session(request.cookies.get(SESSION_COOKIE))}


@router.get("/is-default-password")
async def is_default_password():
    return {"is_default": is_default_password_active()}


@router.get("/current-paths")
async def get_current_paths():
    return {
        "dashboard": CONFIG.get("dashboard_path", "/dashboard"),
        "login": CONFIG.get("login_path", "/login"),
        "sub": CONFIG.get("sub_path", "/sub"),
        "setup": CONFIG.get("setup_path", "/setup"),
    }


@router.get("/get-paths")
async def get_paths(_=Depends(require_auth)):
    return {
        "dashboard_path": CONFIG.get("dashboard_path", "/dashboard"),
        "login_path": CONFIG.get("login_path", "/login"),
        "sub_path": CONFIG.get("sub_path", "/sub"),
        "setup_path": CONFIG.get("setup_path", "/setup"),
    }


@router.post("/update-path")
async def update_path(request: Request, _=Depends(require_auth)):
    body = await request.json()
    updated = {}
    for key in ("dashboard_path", "login_path", "sub_path", "setup_path"):
        if key in body and isinstance(body[key], str):
            val = "/" + body[key].strip().lstrip("/")
            if len(val) >= 2 and not val.startswith("/api") and not val.startswith("/static"):
                CONFIG[key] = val
                updated[key] = val
    await save_state()
    log_activity("settings", f"Updated custom paths: {', '.join(updated.keys())}", "info")
    return {"ok": True, "paths": updated}


@router.post("/change-password")
async def api_change_password(request: Request, _=Depends(require_auth)):
    body = await request.json()
    if hash_password(str(body.get("current_password", ""))) != AUTH["password_hash"]:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new = str(body.get("new_password", ""))
    if len(new) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    AUTH["password_hash"] = hash_password(new)
    await mark_setup_complete()
    await clear_all_sessions()
    await save_state()
    log_activity("auth", "Admin password updated", "ok")
    return {"ok": True, "requires_login": True}

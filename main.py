"""MX-UI v1.0.0 — Multi-Platform VLESS/Trojan (WS & XHTTP) Control Plane."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from app import xray_manager
from app.config import PLATFORM_INFO, PUBLIC_PORT, STATIC_DIR
from app.location import auto_detect_location
from app.proxy import close_proxy_client, router as proxy_router
from app.routes import api_auth, api_links, api_system, pages, sub
from app.state import CONFIG, connections, ensure_default_link, load_state, log_activity, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MX-UI")


async def _xray_stats_loop() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            await xray_manager.sync_stats_to_links()
        except Exception:
            pass


async def _prune_connections_loop() -> None:
    while True:
        await asyncio.sleep(120)
        try:
            stale = []
            for cid, c in list(connections.items()):
                ca = c.get("connected_at")
                if not ca:
                    continue
                try:
                    age = (datetime.now() - datetime.fromisoformat(ca)).total_seconds()
                except Exception:
                    continue
                if age > 7200:
                    stale.append(cid)
            for cid in stale:
                connections.pop(cid, None)
        except Exception as exc:
            logger.debug("[prune] %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await load_state()
    await ensure_default_link()
    CONFIG["panel_location"] = await auto_detect_location()

    xray_ok = False
    for attempt in range(2):
        try:
            xray_ok = await xray_manager.start()
            if xray_ok:
                await xray_manager.diagnose_and_log()
                break
        except Exception as exc:
            logger.warning("[xray] attempt %d failed: %s", attempt + 1, exc)
        await asyncio.sleep(0.5)

    if not xray_ok:
        log_activity("system", f"Panel started on {PLATFORM_INFO['name']} (Xray binary not active)", "warn")
    else:
        log_activity("system", f"MX-UI & Xray Core started on {PLATFORM_INFO['name']}", "ok")

    stats_task = asyncio.create_task(_xray_stats_loop())
    prune_task = asyncio.create_task(_prune_connections_loop())

    try:
        yield
    finally:
        stats_task.cancel()
        prune_task.cancel()
        await save_state()
        await xray_manager.stop()
        await close_proxy_client()


app = FastAPI(title="MX-UI", version="1.0.0", docs_url=None, redoc_url=None, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(proxy_router)
app.include_router(api_auth.router)
app.include_router(api_links.router)
app.include_router(api_system.router)
app.include_router(sub.router)
app.include_router(pages.router)


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("SERVER_PORT") or PUBLIC_PORT)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
        ws_ping_interval=25,
        ws_ping_timeout=20,
    )

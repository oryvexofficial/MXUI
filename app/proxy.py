"""High-performance WebSocket & XHTTP reverse-proxy routes to Xray Core."""
from __future__ import annotations

import asyncio
from datetime import datetime
import inspect
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response, StreamingResponse
import httpx

from app.config import TROJAN_WS_PORT, TROJAN_XHTTP_PORT, WS_PORT, XHTTP_PORT, get_client_ip
from app.state import connections, error_logs, stats

logger = logging.getLogger("MX-UI")
router = APIRouter()

_http_proxy_client: httpx.AsyncClient | None = None


def get_proxy_client() -> httpx.AsyncClient:
    global _http_proxy_client
    if _http_proxy_client is None or _http_proxy_client.is_closed:
        _http_proxy_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=500, max_keepalive_connections=120),
            timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0),
        )
    return _http_proxy_client


async def close_proxy_client() -> None:
    global _http_proxy_client
    if _http_proxy_client and not _http_proxy_client.is_closed:
        await _http_proxy_client.aclose()
    _http_proxy_client = None


def _ws_client_ip(ws: WebSocket) -> str:
    for header in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
        val = ws.headers.get(header)
        if val:
            return val.strip()
    fwd = ws.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


async def _relay_ws(websocket: WebSocket, target_port: int, path: str, transport_name: str) -> None:
    try:
        import websockets as _ws
    except ImportError:
        await websocket.close(code=1011, reason="websockets library unavailable")
        return

    ip = _ws_client_ip(websocket)
    subproto_hdr = websocket.headers.get("sec-websocket-protocol")
    subprotocols = [s.strip() for s in subproto_hdr.split(",") if s.strip()] if subproto_hdr else None

    qs = f"?{websocket.url.query}" if websocket.url.query else ""
    target_url = f"ws://127.0.0.1:{target_port}{path}{qs}"
    fwd_headers = {"X-Forwarded-For": ip}
    if websocket.headers.get("host"):
        fwd_headers["Host"] = websocket.headers["host"]
    ua = websocket.headers.get("user-agent")
    if ua:
        fwd_headers["User-Agent"] = ua

    connect_kwargs: dict = {
        "max_size": None,
        "ping_interval": None,
        "open_timeout": 10,
        "close_timeout": 5,
    }
    if subprotocols:
        connect_kwargs["subprotocols"] = subprotocols
    sig_params = inspect.signature(_ws.connect).parameters
    if "additional_headers" in sig_params:
        connect_kwargs["additional_headers"] = fwd_headers
    elif "extra_headers" in sig_params:
        connect_kwargs["extra_headers"] = fwd_headers

    xray_ws = None
    try:
        xray_ws = await _ws.connect(target_url, **connect_kwargs)
    except Exception as exc:
        logger.warning("[ws-proxy:%s] connect failed: %s", transport_name, exc)
        stats["total_errors"] += 1
        error_logs.append({"error": f"ws connect failed ({transport_name}): {exc}", "time": datetime.now().isoformat()})
        try:
            await websocket.close(code=1011, reason="Upstream unavailable")
        except Exception:
            pass
        return

    await websocket.accept(subprotocol=subprotocols[0] if subprotocols else None)

    conn_id = secrets.token_urlsafe(6)
    connections[conn_id] = {
        "uuid": "xray-session",
        "ip": ip,
        "transport": transport_name,
        "connected_at": datetime.now().isoformat(),
        "bytes": 0,
    }
    stats["total_requests"] += 1

    async def c2x() -> None:
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if data is None and msg.get("text") is not None:
                    data = msg["text"].encode()
                if data:
                    if conn_id in connections:
                        connections[conn_id]["bytes"] += len(data)
                    await xray_ws.send(data)
        except Exception:
            pass
        finally:
            try:
                await xray_ws.close()
            except Exception:
                pass

    async def x2c() -> None:
        try:
            async for m in xray_ws:
                if isinstance(m, bytes):
                    if conn_id in connections:
                        connections[conn_id]["bytes"] += len(m)
                    await websocket.send_bytes(m)
                else:
                    if conn_id in connections:
                        connections[conn_id]["bytes"] += len(m.encode())
                    await websocket.send_text(m)
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    t1 = asyncio.create_task(c2x())
    t2 = asyncio.create_task(x2c())
    try:
        _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pending = {t1, t2}

    for t in pending:
        if not t.done():
            t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    connections.pop(conn_id, None)
    try:
        if xray_ws and not getattr(xray_ws, "closed", True):
            await xray_ws.close()
    except Exception:
        pass
    try:
        await websocket.close()
    except Exception:
        pass


@router.websocket("/ws")
async def ws_vless_proxy(websocket: WebSocket) -> None:
    await _relay_ws(websocket, WS_PORT, "/ws", "vless-ws")


@router.websocket("/ws-trojan")
async def ws_trojan_proxy(websocket: WebSocket) -> None:
    await _relay_ws(websocket, TROJAN_WS_PORT, "/ws-trojan", "trojan-ws")


async def _proxy_xhttp(request: Request, target_port: int, prefix: str, rest: str) -> Response:
    client = get_proxy_client()
    ip = get_client_ip(request)
    qs = f"?{request.url.query}" if request.url.query else ""
    tail = f"/{rest}" if rest else ""
    target_url = f"http://127.0.0.1:{target_port}{prefix}{tail}{qs}"

    hop_by_hop = {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    headers = {k: v for k, v in request.headers.items() if k.lower() not in hop_by_hop}
    headers["X-Forwarded-For"] = ip
    stats["total_requests"] += 1

    conn_id = secrets.token_urlsafe(6)
    connections[conn_id] = {
        "uuid": "xhttp-stream",
        "ip": ip,
        "transport": prefix.lstrip("/"),
        "connected_at": datetime.now().isoformat(),
        "bytes": 0,
    }

    try:
        if request.method == "GET":
            req = client.build_request("GET", target_url, headers=headers)
        else:
            req = client.build_request(request.method, target_url, headers=headers, content=request.stream())
        resp = await client.send(req, stream=True)
    except Exception as exc:
        connections.pop(conn_id, None)
        stats["total_errors"] += 1
        error_logs.append({"error": f"xhttp proxy error: {exc}", "time": datetime.now().isoformat()})
        raise HTTPException(status_code=502, detail=f"XHTTP upstream unavailable: {exc}") from exc

    async def stream_body():
        try:
            async for chunk in resp.aiter_raw():
                if conn_id in connections:
                    connections[conn_id]["bytes"] += len(chunk)
                yield chunk
        finally:
            connections.pop(conn_id, None)
            await resp.aclose()

    resp_headers = {
        "Cache-Control": "no-cache, no-store",
        "X-Accel-Buffering": "no",
    }
    if "content-type" in resp.headers:
        resp_headers["Content-Type"] = resp.headers["content-type"]
    return StreamingResponse(stream_body(), status_code=resp.status_code, headers=resp_headers)


@router.api_route("/xhttp", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
@router.api_route("/xhttp/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
async def xhttp_vless_proxy(request: Request, rest: str = "") -> Response:
    return await _proxy_xhttp(request, XHTTP_PORT, "/xhttp", rest)


@router.api_route("/xhttp-trojan", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
@router.api_route("/xhttp-trojan/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
async def xhttp_trojan_proxy(request: Request, rest: str = "") -> Response:
    return await _proxy_xhttp(request, TROJAN_XHTTP_PORT, "/xhttp-trojan", rest)

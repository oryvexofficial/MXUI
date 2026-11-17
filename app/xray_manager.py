"""Xray Core control plane with multi-inbound support (VLESS/Trojan + WS/XHTTP)."""
from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional
import urllib.request
import zipfile

from app.config import (
    API_PORT,
    BASE_DIR,
    DATA_DIR,
    TROJAN_WS_PORT,
    TROJAN_XHTTP_PORT,
    WS_PORT,
    XHTTP_PORT,
)
from app.state import (
    LINKS,
    LINKS_LOCK,
    hourly_traffic,
    is_link_allowed,
    now_local,
    parse_protocol,
    save_state,
    stats,
)

logger = logging.getLogger("MX-UI")

BIN_NAME = "xray.exe" if sys.platform.startswith("win") else "xray"
LOCAL_BIN_DIR = BASE_DIR / "bin"
DEFAULT_XRAY_VERSION = os.environ.get("XRAY_VERSION", "v25.1.30").strip() or "v25.1.30"

XRAY_BIN: Optional[Path] = None
XRAY_PROC: Optional[subprocess.Popen] = None
XRAY_VERSION: str = ""
XHTTP_TRANSPORT: str = "xhttp"
_WATCHER_TASK: Optional[asyncio.Task] = None


def find_binary() -> Path:
    global XRAY_BIN
    if XRAY_BIN and XRAY_BIN.exists():
        return XRAY_BIN
    for candidate in (
        os.environ.get("XRAY_BIN"),
        "/usr/local/bin/xray",
        "/usr/bin/xray",
        str(LOCAL_BIN_DIR / BIN_NAME),
        str(BASE_DIR / BIN_NAME),
    ):
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists():
            XRAY_BIN = p
            return p
    found = shutil.which("xray") or shutil.which("xray.exe")
    if found:
        XRAY_BIN = Path(found)
        return XRAY_BIN
    raise RuntimeError("Xray binary not found")


def _xray_release_asset() -> Optional[str]:
    sys_name = platform.system()
    arch = platform.machine().lower()
    if sys_name == "Linux":
        if arch in ("x86_64", "amd64"):
            return "Xray-linux-64.zip"
        if arch in ("aarch64", "arm64"):
            return "Xray-linux-arm64-v8a.zip"
        if arch.startswith("armv7"):
            return "Xray-linux-arm32-v7a.zip"
    elif sys_name == "Darwin":
        if arch in ("arm64", "aarch64"):
            return "Xray-macos-arm64-v8a.zip"
        if arch in ("x86_64", "amd64"):
            return "Xray-macos-64.zip"
    return None


def ensure_binary_sync() -> Optional[Path]:
    """Ensure Xray binary exists, auto-downloading into ./bin/xray if missing."""
    try:
        return find_binary()
    except RuntimeError:
        pass

    asset = _xray_release_asset()
    if not asset:
        logger.warning("[xray] unsupported OS/arch for auto-install: %s/%s", platform.system(), platform.machine())
        return None

    url = f"https://github.com/XTLS/Xray-core/releases/download/{DEFAULT_XRAY_VERSION}/{asset}"
    dest = LOCAL_BIN_DIR / BIN_NAME
    try:
        LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("[xray] binary missing; downloading %s ...", url)
        req = urllib.request.Request(url, headers={"User-Agent": "MX-UI/1.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            member = next((n for n in zf.namelist() if n.endswith("/xray") or n == "xray"), None)
            if not member:
                raise RuntimeError("xray binary not found in release archive")
            dest.write_bytes(zf.read(member))
        dest.chmod(0o755)
        global XRAY_BIN
        XRAY_BIN = dest
        logger.info("[xray] auto-installed at %s", dest)
        return dest
    except Exception as exc:
        logger.warning("[xray] auto-install failed: %s", exc)
        return None


def inbound_port_for_protocol(proto: str, is_default: bool = False) -> int:
    if is_default or proto == "all":
        return WS_PORT
    family, transport, _ = parse_protocol(proto)
    if family == "trojan":
        return TROJAN_XHTTP_PORT if transport == "xhttp" else TROJAN_WS_PORT
    return XHTTP_PORT if transport == "xhttp" else WS_PORT


def _detect_version() -> None:
    global XRAY_VERSION, XHTTP_TRANSPORT
    try:
        binary = find_binary()
        r = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout or "") + (r.stderr or "")
        XRAY_VERSION = out.splitlines()[0].strip() if out else "unknown"
        logger.info("[xray] detected: %s", XRAY_VERSION)

        m = re.search(r"Xray\s+(\d+)\.(\d+)", XRAY_VERSION)
        if m:
            maj = int(m.group(1))
            min_ = int(m.group(2))
            if maj == 1 or (maj < 24 and min_ < 10):
                XHTTP_TRANSPORT = "splithttp"
            else:
                XHTTP_TRANSPORT = "xhttp"
        logger.info("[xray] xhttp transport = %s", XHTTP_TRANSPORT)
    except Exception as exc:
        logger.warning("[xray] version detection failed: %s", exc)
        XHTTP_TRANSPORT = "xhttp"


def _build_config() -> dict:
    vless_ws_clients = []
    vless_xhttp_clients = []
    trojan_ws_clients = []
    trojan_xhttp_clients = []

    for uid, link in list(LINKS.items()):
        if not is_link_allowed(link):
            continue
        proto = link.get("protocol", "vless-ws")
        if link.get("is_default") or proto == "all":
            vless_ws_clients.append({"id": uid, "email": f"{uid}@vless-ws", "level": 0})
            vless_xhttp_clients.append({"id": uid, "email": f"{uid}@vless-xhttp", "level": 0})
            trojan_ws_clients.append({"password": uid, "email": f"{uid}@trojan-ws", "level": 0})
            trojan_xhttp_clients.append({"password": uid, "email": f"{uid}@trojan-xhttp", "level": 0})
        else:
            family, transport, _ = parse_protocol(proto)
            if family == "trojan":
                if transport == "xhttp":
                    trojan_xhttp_clients.append({"password": uid, "email": f"{uid}@trojan-xhttp", "level": 0})
                else:
                    trojan_ws_clients.append({"password": uid, "email": f"{uid}@trojan-ws", "level": 0})
            else:
                if transport == "xhttp":
                    vless_xhttp_clients.append({"id": uid, "email": f"{uid}@vless-xhttp", "level": 0})
                else:
                    vless_ws_clients.append({"id": uid, "email": f"{uid}@vless-ws", "level": 0})

    xhttp_key = "splithttpSettings" if XHTTP_TRANSPORT == "splithttp" else "xhttpSettings"

    inbounds = [
        {
            "tag": "vless-ws",
            "listen": "127.0.0.1",
            "port": WS_PORT,
            "protocol": "vless",
            "settings": {"clients": vless_ws_clients, "decryption": "none"},
            "streamSettings": {"network": "ws", "wsSettings": {"path": "/ws"}},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        },
        {
            "tag": "vless-xhttp",
            "listen": "127.0.0.1",
            "port": XHTTP_PORT,
            "protocol": "vless",
            "settings": {"clients": vless_xhttp_clients, "decryption": "none"},
            "streamSettings": {"network": XHTTP_TRANSPORT, xhttp_key: {"path": "/xhttp"}},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        },
        {
            "tag": "trojan-ws",
            "listen": "127.0.0.1",
            "port": TROJAN_WS_PORT,
            "protocol": "trojan",
            "settings": {"clients": trojan_ws_clients},
            "streamSettings": {"network": "ws", "wsSettings": {"path": "/ws-trojan"}},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        },
        {
            "tag": "trojan-xhttp",
            "listen": "127.0.0.1",
            "port": TROJAN_XHTTP_PORT,
            "protocol": "trojan",
            "settings": {"clients": trojan_xhttp_clients},
            "streamSettings": {"network": XHTTP_TRANSPORT, xhttp_key: {"path": "/xhttp-trojan"}},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        },
        {
            "tag": "api",
            "listen": "127.0.0.1",
            "port": API_PORT,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        },
    ]

    return {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "services": ["StatsService", "HandlerService"]},
        "stats": {},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True, "connIdle": 300}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "routing": {"rules": [{"type": "field", "inboundTag": ["api"], "outboundTag": "api"}]},
        "inbounds": inbounds,
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }


def _write_config() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = _build_config()
    path = DATA_DIR / "xray_config.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _validate_config(cfg_path: Path) -> tuple[bool, str]:
    binary = find_binary()
    try:
        r = subprocess.run(
            [str(binary), "run", "-c", str(cfg_path), "-test"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "xray -test timed out"
    except Exception as exc:
        return False, str(exc)


def _spawn() -> bool:
    global XRAY_PROC, XHTTP_TRANSPORT
    try:
        binary = find_binary()
    except RuntimeError as exc:
        logger.warning("[xray] binary not found (%s) — running control plane in standalone mode", exc)
        return False

    cfg_path = _write_config()
    ok, msg = _validate_config(cfg_path)
    if not ok:
        logger.error("[xray] config invalid: %s", msg)
        if "unknown transport protocol" in msg.lower():
            alt = "splithttp" if XHTTP_TRANSPORT == "xhttp" else "xhttp"
            logger.info("[xray] retrying with transport '%s'", alt)
            XHTTP_TRANSPORT = alt
            cfg_path = _write_config()
            ok, msg = _validate_config(cfg_path)
        if not ok:
            logger.error("[xray] config validation failed: %s", msg)
            return False

    log_path = DATA_DIR / "xray_stdout.log"
    stdout_log = open(log_path, "ab", buffering=0)
    stdout_log.write(f"\n\n=== xray start {datetime.now().isoformat()} ===\n".encode())

    kwargs: dict = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x08000000

    XRAY_PROC = subprocess.Popen(
        [str(binary), "run", "-c", str(cfg_path)],
        stdout=stdout_log,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
    time.sleep(0.8)
    rc = XRAY_PROC.poll()
    if rc is not None:
        logger.error("[xray] exited immediately with code %s", rc)
        return False

    logger.info(
        "[xray] started pid=%s ws=%s xhttp=%s trojan_ws=%s trojan_xhttp=%s api=%s",
        XRAY_PROC.pid,
        WS_PORT,
        XHTTP_PORT,
        TROJAN_WS_PORT,
        TROJAN_XHTTP_PORT,
        API_PORT,
    )
    return True


async def _wait_listen(host: str, port: int, timeout: float = 6.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        s = socket.socket()
        s.settimeout(0.25)
        try:
            if s.connect_ex((host, port)) == 0:
                return True
        finally:
            s.close()
        await asyncio.sleep(0.25)
    return False


async def start() -> bool:
    global _WATCHER_TASK
    await asyncio.to_thread(ensure_binary_sync)
    _detect_version()
    spawned = _spawn()
    if not spawned:
        return False

    await asyncio.gather(
        _wait_listen("127.0.0.1", WS_PORT, timeout=6.0),
        _wait_listen("127.0.0.1", XHTTP_PORT, timeout=6.0),
        _wait_listen("127.0.0.1", TROJAN_WS_PORT, timeout=6.0),
        _wait_listen("127.0.0.1", TROJAN_XHTTP_PORT, timeout=6.0),
    )

    if _WATCHER_TASK is None or _WATCHER_TASK.done():
        _WATCHER_TASK = asyncio.create_task(_config_watcher())
    return True


async def stop() -> None:
    global XRAY_PROC, _WATCHER_TASK
    if _WATCHER_TASK and not _WATCHER_TASK.done():
        _WATCHER_TASK.cancel()
        try:
            await _WATCHER_TASK
        except asyncio.CancelledError:
            pass
    _WATCHER_TASK = None

    if XRAY_PROC and XRAY_PROC.poll() is None:
        try:
            XRAY_PROC.terminate()
            try:
                XRAY_PROC.wait(timeout=5)
            except subprocess.TimeoutExpired:
                XRAY_PROC.kill()
                XRAY_PROC.wait(timeout=2)
        except Exception as exc:
            logger.warning("[xray] stop error: %s", exc)
    XRAY_PROC = None


_RELOAD_LOCK = asyncio.Lock()


async def reload_config() -> None:
    async with _RELOAD_LOCK:
        try:
            find_binary()
        except RuntimeError:
            return
        await stop()
        if _spawn():
            await asyncio.gather(
                _wait_listen("127.0.0.1", WS_PORT, timeout=5.0),
                _wait_listen("127.0.0.1", XHTTP_PORT, timeout=5.0),
                _wait_listen("127.0.0.1", TROJAN_WS_PORT, timeout=5.0),
                _wait_listen("127.0.0.1", TROJAN_XHTTP_PORT, timeout=5.0),
            )


async def _config_watcher() -> None:
    last = None
    while True:
        await asyncio.sleep(3)
        try:
            async with LINKS_LOCK:
                snap = sorted(
                    (uid, is_link_allowed(l), l.get("protocol", "vless-ws"))
                    for uid, l in LINKS.items()
                )
            h = hashlib.sha256(repr(snap).encode()).hexdigest()
            if h != last:
                if last is not None:
                    await reload_config()
                last = h
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[xray] watcher error: %s", exc)


async def _api_call(*args: str) -> str:
    binary = find_binary()
    proc = await asyncio.create_subprocess_exec(
        str(binary),
        "api",
        *args,
        "--server",
        f"127.0.0.1:{API_PORT}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode().strip() or "xray api failed")
    return out.decode()


async def query_stats(reset: bool = True) -> dict:
    args = ["--reset", "statsquery", "--pattern", "user>>>"] if reset else ["statsquery", "--pattern", "user>>>"]
    out = await _api_call(*args)
    parsed: dict = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or ">>>" not in line:
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        key, val_s = parts
        try:
            val = int(val_s)
        except ValueError:
            continue
        seg = key.split(">>>")
        if len(seg) == 4 and seg[0] == "user" and seg[2] == "traffic":
            uid = seg[1].split("@", 1)[0]
            direction = seg[3]
            parsed.setdefault(uid, {})[direction] = parsed.get(uid, {}).get(direction, 0) + val
    return parsed


async def sync_stats_to_links() -> None:
    if not (XRAY_PROC and XRAY_PROC.poll() is None):
        return
    try:
        deltas = await asyncio.wait_for(query_stats(reset=True), timeout=4.0)
    except Exception:
        return
    if not deltas:
        return

    changed = False
    auto_disabled: list[str] = []
    async with LINKS_LOCK:
        for uid, d in deltas.items():
            link = LINKS.get(uid)
            if not link:
                continue
            total = int(d.get("uplink", 0)) + int(d.get("downlink", 0))
            if total <= 0:
                continue
            link["used_bytes"] = int(link.get("used_bytes", 0) or 0) + total
            link["last_used"] = datetime.now().isoformat()
            stats["total_bytes"] = int(stats.get("total_bytes", 0) or 0) + total
            hourly_traffic[now_local().strftime("%H:00")] += total
            changed = True
            lb = int(link.get("limit_bytes", 0) or 0)
            if lb > 0 and link["used_bytes"] >= lb and link.get("active", True):
                link["active"] = False
                auto_disabled.append(link.get("label", uid))

    if changed:
        await save_state()
        if auto_disabled:
            await reload_config()
            for lbl in auto_disabled:
                logger.info("[xray] auto-disabled over-quota config: %s", lbl)


def port_status() -> dict:
    def probe(host: str, port: int) -> bool:
        s = socket.socket()
        s.settimeout(0.2)
        try:
            return s.connect_ex((host, port)) == 0
        finally:
            s.close()

    is_alive = bool(XRAY_PROC and XRAY_PROC.poll() is None)
    return {
        "xray_running": is_alive,
        "xray_version": XRAY_VERSION or "not installed",
        "xhttp_transport": XHTTP_TRANSPORT,
        "xray_pid": XRAY_PROC.pid if is_alive and XRAY_PROC else None,
        "xray_returncode": XRAY_PROC.poll() if XRAY_PROC else None,
        "listening": {
            f"127.0.0.1:{WS_PORT}": probe("127.0.0.1", WS_PORT),
            f"127.0.0.1:{XHTTP_PORT}": probe("127.0.0.1", XHTTP_PORT),
            f"127.0.0.1:{TROJAN_WS_PORT}": probe("127.0.0.1", TROJAN_WS_PORT),
            f"127.0.0.1:{TROJAN_XHTTP_PORT}": probe("127.0.0.1", TROJAN_XHTTP_PORT),
            f"127.0.0.1:{API_PORT}": probe("127.0.0.1", API_PORT),
        },
    }


async def diagnose_and_log(delay: float = 0.8) -> None:
    await asyncio.sleep(delay)
    st = port_status()
    lines = ["[xray] status:"]
    for k, v in st["listening"].items():
        lines.append(f"  {'OK' if v else 'DOWN'} {k}")
    lines.append(
        f"  version={st['xray_version']} transport={st['xhttp_transport']} running={st['xray_running']} pid={st['xray_pid']}"
    )
    logger.info("\n".join(lines))

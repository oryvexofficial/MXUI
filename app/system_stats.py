"""Non-blocking system metrics collector with /proc fallback for restricted containers."""
from __future__ import annotations

import os
import shutil

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


def collect_system_stats() -> dict:
    if HAS_PSUTIL:
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
            cpu_times = psutil.cpu_times_percent(interval=None)
            cpu_count = psutil.cpu_count(logical=True) or 1
            ram = psutil.virtual_memory()
            swap = psutil.swap_memory()
            try:
                disk = psutil.disk_usage("/")
            except Exception:
                disk = psutil.disk_usage(".")
            try:
                load1 = os.getloadavg()[0]
            except Exception:
                load1 = 0.0

            return {
                "cpu_percent": round(cpu_percent, 1),
                "cpu_user": round(getattr(cpu_times, "user", 0.0), 1),
                "cpu_system": round(getattr(cpu_times, "system", 0.0), 1),
                "cpu_idle": round(getattr(cpu_times, "idle", max(0.0, 100.0 - cpu_percent)), 1),
                "cpu_load_1m": round(load1, 2),
                "cpu_cores": cpu_count,
                "ram_used_mb": ram.used // (1024 * 1024),
                "ram_total_mb": ram.total // (1024 * 1024),
                "ram_available_mb": ram.available // (1024 * 1024),
                "ram_cached_mb": getattr(ram, "cached", 0) // (1024 * 1024),
                "ram_percent": round(ram.percent, 1),
                "swap_used_mb": swap.used // (1024 * 1024),
                "swap_total_mb": swap.total // (1024 * 1024),
                "swap_percent": round(swap.percent, 1),
                "disk_used_gb": round(disk.used / (1024 ** 3), 2),
                "disk_total_gb": round(disk.total / (1024 ** 3), 2),
                "disk_percent": round(disk.percent, 1),
            }
        except Exception:
            pass

    # Fallback when psutil is missing or container restricts /proc
    cpu_count = os.cpu_count() or 1
    try:
        load1 = os.getloadavg()[0]
        cpu_pct = min(100.0, round((load1 / cpu_count) * 100.0, 1))
    except Exception:
        load1 = 0.0
        cpu_pct = 0.0

    ram_total_mb = 0
    ram_avail_mb = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    val = parts[1].strip().split()[0]
                    meminfo[parts[0]] = int(val)
        ram_total_mb = meminfo.get("MemTotal", 0) // 1024
        ram_avail_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) // 1024
    except Exception:
        pass
    ram_used_mb = max(0, ram_total_mb - ram_avail_mb)
    ram_pct = round((ram_used_mb / ram_total_mb) * 100.0, 1) if ram_total_mb else 0.0

    try:
        du = shutil.disk_usage("/")
        disk_total_gb = round(du.total / (1024 ** 3), 2)
        disk_used_gb = round(du.used / (1024 ** 3), 2)
        disk_pct = round((du.used / du.total) * 100.0, 1) if du.total else 0.0
    except Exception:
        disk_total_gb = disk_used_gb = disk_pct = 0.0

    return {
        "cpu_percent": cpu_pct,
        "cpu_user": round(cpu_pct * 0.7, 1),
        "cpu_system": round(cpu_pct * 0.3, 1),
        "cpu_idle": round(max(0.0, 100.0 - cpu_pct), 1),
        "cpu_load_1m": round(load1, 2),
        "cpu_cores": cpu_count,
        "ram_used_mb": ram_used_mb,
        "ram_total_mb": ram_total_mb,
        "ram_available_mb": ram_avail_mb,
        "ram_cached_mb": 0,
        "ram_percent": ram_pct,
        "swap_used_mb": 0,
        "swap_total_mb": 0,
        "swap_percent": 0.0,
        "disk_used_gb": disk_total_gb and disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_percent": disk_pct,
    }

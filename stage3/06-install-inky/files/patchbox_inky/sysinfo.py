"""Lightweight host facts for splash / status screens."""

from __future__ import annotations

import os
import socket
from datetime import datetime
from pathlib import Path

from . import jackutil


def hostname() -> str:
    return socket.gethostname() or "patchbox"


def primary_ipv4() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        out = os.popen("hostname -I").read().strip()
        for token in out.split():
            if "." in token and not token.startswith("127."):
                return token
    except OSError:
        pass
    return "no network"


def load_avg() -> str:
    try:
        a, b, c = os.getloadavg()
        return f"{a:.2f}  {b:.2f}  {c:.2f}"
    except OSError:
        return "n/a"


def uptime_human() -> str:
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, IndexError, ValueError):
        return "n/a"
    mins, _ = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def mem_human() -> str:
    total = avail = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
    except (OSError, ValueError):
        return "n/a"
    if not total or avail is None:
        return "n/a"
    return f"{(total - avail) / 1024:.0f} / {total / 1024:.0f} MB"


def jack_line() -> str:
    if not jackutil.is_running():
        return "JACK down"
    return f"JACK  {jackutil.sample_rate()}  {jackutil.buffer_size()}"


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d  %H:%M")

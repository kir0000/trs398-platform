"""Who may open the program over the network: a list of allowed addresses (settings or TRS_ALLOWED_NETWORKS).

An empty list allows everybody (the default). A list holds single addresses and networks, separated by commas, semicolons, spaces or
lines:  192.168.1.0/24, 10.0.0.15.  The computer itself (127.0.0.1, ::1) is always allowed, so the administrator cannot lock himself out.
"""
from __future__ import annotations

import ipaddress
import os
import re
import time

from app import settings

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
_SPLIT = re.compile(r"[,;\s]+")
_cache: dict = {"key": None, "networks": []}


def parse(text: str) -> tuple[list[Network], list[str]]:
    """The networks of a text and the entries that are not addresses."""
    networks, bad = [], []
    for entry in _SPLIT.split(text or ""):
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            bad.append(entry)
    return networks, bad


def client_address(host: str | None):
    """The address of a request as an ip_address (an IPv4 address inside IPv6 is unwrapped); None if it is not an address."""
    try:
        ip = ipaddress.ip_address((host or "").split("%")[0])
    except ValueError:
        return None
    return ip.ipv4_mapped if getattr(ip, "ipv4_mapped", None) else ip


def configured() -> list[Network]:
    """The allowed networks now; re-read when the settings file changes."""
    env = os.environ.get("TRS_ALLOWED_NETWORKS")
    try:
        stamp = settings.path().stat().st_mtime_ns
    except OSError:
        stamp = None
    key = (env, stamp, str(settings.path()))
    if _cache["key"] != key:
        text = env if env is not None else str(settings.load().get("allowed_networks") or "")
        _cache.update(key=key, networks=parse(text)[0])
    return _cache["networks"]


def is_allowed(host: str | None, networks: list[Network] | None = None) -> bool:
    networks = configured() if networks is None else networks
    if not networks:
        return True
    ip = client_address(host)
    if ip is None:
        return False                                                    # a name instead of an address: not trusted when a list is set
    return ip.is_loopback or any(ip in n for n in networks)


# ---- the log of refusals: one record per address per hour, so that a scan does not flood the audit log
_denied: dict[str, float] = {}


def should_log_denial(host: str | None, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    key = host or "?"
    if now - _denied.get(key, 0) < 3600:
        return False
    if len(_denied) > 1000:
        _denied.clear()
    _denied[key] = now
    return True

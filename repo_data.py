from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time

import requests

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
REMOTE_BASE = 'https://raw.githubusercontent.com/Richophie/swing-lab/main/static'
REMOTE_TTL_SECONDS = 20.0
REMOTE_CONNECT_TIMEOUT = 1.5
REMOTE_READ_TIMEOUT = 2.5

_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}
_session = requests.Session()


def remote_enabled() -> bool:
    override = str(os.getenv('SWING_LAB_REMOTE_DATA') or '').strip().lower()
    if override in {'1', 'true', 'yes', 'on'}:
        return True
    if override in {'0', 'false', 'no', 'off'}:
        return False
    return str(os.getenv('RENDER') or '').strip().lower() == 'true'


def _local(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return deepcopy(default)


def _remote_json(name: str):
    now = time.monotonic()
    with _lock:
        cached = _cache.get(name)
        if cached and now - cached[0] < REMOTE_TTL_SECONDS:
            return deepcopy(cached[1])
    response = _session.get(
        f'{REMOTE_BASE}/{name}',
        timeout=(REMOTE_CONNECT_TIMEOUT, REMOTE_READ_TIMEOUT),
        headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'},
    )
    response.raise_for_status()
    data = response.json()
    with _lock:
        _cache[name] = (now, data)
    return deepcopy(data)


def load_json(path: str | Path, default, *, prefer_remote: bool = True):
    """Read mutable scanner JSON from GitHub on Render, with local fallback.

    GitHub Actions commits live-scan/journal data with [skip render] so the web
    service should not require a redeploy for each data refresh. Only fixed files
    under static/ are eligible for remote reads; runtime Paper files always remain
    local/browser-scoped.
    """
    p = Path(path)
    try:
        is_static = p.resolve().parent == STATIC.resolve()
    except Exception:
        is_static = False
    if prefer_remote and is_static and remote_enabled():
        try:
            return _remote_json(p.name)
        except Exception:
            pass
    return _local(p, default)


def clear_cache() -> None:
    with _lock:
        _cache.clear()

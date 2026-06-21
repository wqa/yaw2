"""Local CLI configuration — keeps secret endpoints out of the repo.

Values are read from environment variables first, then `~/.yaw/config` (a simple
`key = value` file, gitignored along with the rest of `~/.yaw`), then a harmless
placeholder default. Create `~/.yaw/config` with, e.g.:

    signal_url = wss://your-anchor.example/<secret-path>/signal
    default_net = your-network-name
"""

from __future__ import annotations

import os

CONFIG_PATH = os.path.expanduser("~/.yaw/config")


def _file() -> dict:
    out: dict = {}
    try:
        with open(CONFIG_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return out


def _get(key: str, env: str, default: str) -> str:
    return os.environ.get(env) or _file().get(key) or default


def signal_url() -> str:
    return _get("signal_url", "YAW_SIGNAL", "wss://your-anchor.example/<secret-path>/signal")


def default_net() -> str:
    return _get("default_net", "YAW_NET", "")


def stun_url() -> str:
    return _get("stun_url", "YAW_STUN", "stun:your-anchor.example:3478")

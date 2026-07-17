"""Stop the local Atlas API process for the configured API URL."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PATH = PROJECT_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.core.config import get_settings


def _health_is_atlas(api_url: str) -> bool:
    try:
        with urlopen(f"{api_url.rstrip('/')}/api/v1/health", timeout=3) as response:
            payload = json.loads(response.read().decode())
            return response.status == 200 and payload.get("service") == "atlas-api"
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return False


def _windows_listener_pids(port: int) -> set[int]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local_address, state, pid_text = parts[1], parts[3], parts[4]
        if state.upper() != "LISTENING":
            continue
        if local_address.rsplit(":", 1)[-1] != str(port):
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return pids


def listener_pids(port: int) -> set[int]:
    if os.name == "nt":
        return _windows_listener_pids(port)
    result = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, check=False)
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        try:
            pids.add(int(line.strip()))
        except ValueError:
            continue
    return pids


def stop_api() -> int:
    settings = get_settings()
    parsed = urlparse(settings.api_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    pids = listener_pids(port)
    if not pids:
        print(f"Atlas API is not listening on port {port}.")
        return 0
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        print(f"Refusing to stop non-local Atlas API URL: {settings.api_url}")
        return 1
    if not _health_is_atlas(settings.api_url):
        print(f"Port {port} is in use, but it did not identify as Atlas. Nothing was stopped.")
        return 1
    stopped: list[int] = []
    for pid in sorted(pids):
        try:
            if os.name == "nt":
                result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    print(f"Could not stop process {pid}: {(result.stderr or result.stdout).strip()}")
                    return 1
            else:
                os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except PermissionError:
            print(f"Permission denied while stopping process {pid}.")
            return 1
        except ProcessLookupError:
            continue
    if stopped:
        print(f"Stopped Atlas API process(es): {', '.join(str(pid) for pid in stopped)}")
    else:
        print("Atlas API was already stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(stop_api())

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ADAPTER_ROOT = Path(__file__).resolve().parents[1] / "adapters" / "hermes" / "memory_palace"
sys.path.insert(0, str(ADAPTER_ROOT))

from client import MemoryPalaceClient, MemoryPalaceError  # noqa: E402


class MemoryPalaceClientTests(unittest.TestCase):
    def test_round_trip_validates_and_returns_result(self) -> None:
        connection = FakeSocket()
        with patch("client.socket.socket", return_value=connection):
            result = MemoryPalaceClient(Path("/run/palace.sock")).call("health")
            self.assertEqual(result, {"status": "ok"})

    def test_unavailable_daemon_has_actionable_error(self) -> None:
        connection = FakeSocket(connect_error=FileNotFoundError("missing"))
        with patch("client.socket.socket", return_value=connection):
            client = MemoryPalaceClient(Path("/run/missing.sock"), timeout=0.1)
            with self.assertRaisesRegex(MemoryPalaceError, "unavailable"):
                client.call("health")


class FakeSocket:
    def __init__(self, connect_error: OSError | None = None) -> None:
        self.connect_error = connect_error
        self.response = b""

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def settimeout(self, _: float) -> None:
        return None

    def connect(self, _: str) -> None:
        if self.connect_error:
            raise self.connect_error

    def sendall(self, payload: bytes) -> None:
        request = json.loads(payload)
        self.response = json.dumps(
            {
                "version": 1,
                "id": request["id"],
                "ok": True,
                "result": {"status": "ok"},
            }
        ).encode() + b"\n"

    def recv(self, _: int) -> bytes:
        response, self.response = self.response, b""
        return response


if __name__ == "__main__":
    unittest.main()

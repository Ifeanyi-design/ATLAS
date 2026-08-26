"""Standard-library client for the Memory Palace Unix-socket protocol."""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 64 * 1024 * 1024


class MemoryPalaceError(RuntimeError):
    """The daemon was unavailable or returned a protocol error."""


class MemoryPalaceClient:
    def __init__(self, socket_path: Path, timeout: float = 5.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = str(uuid.uuid4())
        payload = json.dumps(
            {
                "version": PROTOCOL_VERSION,
                "id": request_id,
                "method": method,
                "params": params or {},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(payload) > MAX_FRAME_BYTES:
            raise MemoryPalaceError("request exceeds the protocol frame limit")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(str(self.socket_path))
                connection.sendall(payload)
                response_bytes = self._read_frame(connection)
        except OSError as error:
            raise MemoryPalaceError(
                f"Memory Palace is unavailable at {self.socket_path}: {error}"
            ) from error

        try:
            response = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MemoryPalaceError("daemon returned invalid JSON") from error
        if response.get("version") != PROTOCOL_VERSION:
            raise MemoryPalaceError("daemon returned an unsupported protocol version")
        if response.get("id") != request_id:
            raise MemoryPalaceError("daemon response id did not match the request")
        if not response.get("ok"):
            body = response.get("error") or {}
            raise MemoryPalaceError(
                f"{body.get('code', 'UNKNOWN')}: {body.get('message', 'request failed')}"
            )
        return response.get("result")

    @staticmethod
    def _read_frame(connection: socket.socket) -> bytes:
        chunks: list[bytes] = []
        length = 0
        while True:
            chunk = connection.recv(min(65536, MAX_FRAME_BYTES + 1 - length))
            if not chunk:
                raise MemoryPalaceError("daemon closed the socket without a response")
            newline = chunk.find(b"\n")
            if newline >= 0:
                chunks.append(chunk[:newline])
                return b"".join(chunks)
            chunks.append(chunk)
            length += len(chunk)
            if length > MAX_FRAME_BYTES:
                raise MemoryPalaceError("daemon response exceeds the protocol frame limit")

"""Hermes MemoryProvider adapter for the Rust Memory Palace daemon."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from agent.memory_provider import MemoryProvider

from .client import MemoryPalaceClient


def _project_name(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    configured = os.environ.get("MEMORY_PALACE_PROJECT", "").strip()
    if configured:
        return configured
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate.name
    return current.name or "default"


class MemoryPalaceMemoryProvider(MemoryProvider):
    pre_compress_checkpoint_api_version = 2

    def __init__(self) -> None:
        self._client: MemoryPalaceClient | None = None
        self._session_id = ""
        self._project = "default"

    @property
    def name(self) -> str:
        return "memory-palace"

    def is_available(self) -> bool:
        return os.name == "posix" and shutil.which("memory-palace") is not None

    def unavailable_reason(self) -> str:
        return "Install the memory-palace Linux binary and ensure it is on PATH."

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = Path(kwargs["hermes_home"])
        self._session_id = session_id
        self._project = _project_name(kwargs.get("project"))
        self._client = MemoryPalaceClient(
            hermes_home / "memory-palace" / "run" / "memory-palace.sock"
        )
        self._call("health")
        self._call("project.resolve", {"name": self._project})

    def get_config_schema(self) -> list[dict[str, Any]]:
        return []

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memory_palace_log_decision",
                "description": "Save a material project decision and its rationale.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "reason": {"type": "string"},
                        "affected_files": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "importance": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "default": 3,
                        },
                    },
                    "required": ["decision", "reason"],
                },
            },
            {
                "name": "memory_palace_search",
                "description": "Search active decisions in the current project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def handle_tool_call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> str:
        if tool_name == "memory_palace_log_decision":
            params = {
                **args,
                "project": self._project,
                "session_id": kwargs.get("session_id") or self._session_id,
            }
            result = self._call("memory.log_decision", params)
        elif tool_name == "memory_palace_search":
            result = self._call(
                "memory.search", {**args, "project": self._project}
            )
        else:
            return json.dumps({"ok": False, "error": f"unknown tool {tool_name}"})
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        rewound: bool = False,
        **kwargs: Any,
    ) -> None:
        self._session_id = new_session_id

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        content = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        result = self._call(
            "checkpoint.archive",
            {
                "project": self._project,
                "session_id": self._session_id,
                "content": content,
            },
        )
        return str(result["checkpoint_id"])

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._client is None:
            raise RuntimeError("Memory Palace provider is not initialized")
        return self._client.call(method, params)


def register(ctx: Any) -> None:
    ctx.register_memory_provider(MemoryPalaceMemoryProvider())

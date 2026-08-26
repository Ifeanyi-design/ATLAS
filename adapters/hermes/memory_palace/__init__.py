"""Hermes MemoryProvider adapter for the Rust Memory Palace daemon."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agent.memory_provider import MemoryProvider

from .client import MemoryPalaceClient

logger = logging.getLogger(__name__)


def _binary_path(hermes_home: Path | None = None) -> Path | None:
    configured = os.environ.get("MEMORY_PALACE_BINARY", "").strip()
    if configured:
        return Path(configured)
    if hermes_home is None:
        try:
            from hermes_constants import get_hermes_home

            hermes_home = Path(get_hermes_home())
        except (ImportError, OSError):
            hermes_home = None
    if hermes_home is not None:
        installed = hermes_home / "memory-palace" / "bin" / "memory-palace"
        if installed.is_file():
            return installed
    discovered = shutil.which("memory-palace")
    return Path(discovered) if discovered else None


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
        self._binary: Path | None = None
        self._palace_home: Path | None = None
        self._session_id = ""
        self._project = "default"
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="memory-palace-sync"
        )

    @property
    def name(self) -> str:
        return "memory-palace"

    def is_available(self) -> bool:
        return os.name == "posix" and _binary_path() is not None

    def unavailable_reason(self) -> str:
        return "Install the memory-palace Linux binary and ensure it is on PATH."

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = Path(kwargs["hermes_home"])
        self._palace_home = hermes_home / "memory-palace"
        self._binary = _binary_path(hermes_home)
        if self._binary is None:
            raise RuntimeError(self.unavailable_reason())
        self._session_id = session_id
        self._project = _project_name(kwargs.get("project"))
        self._client = MemoryPalaceClient(
            self._palace_home / "run" / "memory-palace.sock"
        )
        self._ensure_daemon()
        self._call("project.resolve", {"name": self._project})

    def _ensure_daemon(self) -> None:
        try:
            self._call("health")
            return
        except RuntimeError:
            pass
        assert self._binary is not None
        assert self._palace_home is not None
        log_directory = self._palace_home / "log"
        log_directory.mkdir(parents=True, exist_ok=True)
        with (log_directory / "daemon.log").open("ab") as log_file:
            subprocess.Popen(
                [str(self._binary), "--home", str(self._palace_home), "serve"],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        last_error: RuntimeError | None = None
        for _ in range(30):
            try:
                self._call("health")
                return
            except RuntimeError as error:
                last_error = error
                time.sleep(0.1)
        raise RuntimeError(
            f"Memory Palace daemon did not start; see {log_directory / 'daemon.log'}"
        ) from last_error

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
            {
                "name": "memory_palace_get",
                "description": "Get one saved decision by ID.",
                "parameters": _id_parameters("decision_id"),
            },
            {
                "name": "memory_palace_edit_decision",
                "description": "Correct an existing project decision by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision_id": {"type": "string"},
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
                        },
                    },
                    "required": ["decision_id"],
                },
            },
            {
                "name": "memory_palace_remove",
                "description": "Remove one decision, or all project memory with exact confirmation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision_id": {"type": "string"},
                        "delete_all": {"type": "boolean", "default": False},
                        "confirmation": {"type": "string"},
                    },
                },
            },
            {
                "name": "memory_palace_override_conflict",
                "description": "Record the reason for deliberately overriding a conflict warning.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "conflict_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["conflict_id", "reason"],
                },
            },
            {
                "name": "memory_palace_get_archived_turn",
                "description": "Recover one archived turn and its raw evidence.",
                "parameters": _id_parameters("turn_id"),
            },
            {
                "name": "memory_palace_get_tool_event",
                "description": "Recover one archived tool result and its raw evidence.",
                "parameters": _id_parameters("event_id"),
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
        elif tool_name == "memory_palace_get":
            result = self._call("memory.get", {**args, "project": self._project})
        elif tool_name == "memory_palace_edit_decision":
            result = self._call(
                "memory.edit_decision", {**args, "project": self._project}
            )
        elif tool_name == "memory_palace_remove":
            result = self._call("memory.remove", {**args, "project": self._project})
        elif tool_name == "memory_palace_override_conflict":
            result = self._call(
                "conflict.override", {**args, "project": self._project}
            )
        elif tool_name == "memory_palace_get_archived_turn":
            result = self._call("turn.get", {**args, "project": self._project})
        elif tool_name == "memory_palace_get_tool_event":
            result = self._call(
                "tool_event.get", {**args, "project": self._project}
            )
        else:
            return json.dumps({"ok": False, "error": f"unknown tool {tool_name}"})
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        turn_messages = _current_turn_messages(messages, user_content, assistant_content)
        payload = {
            "project": self._project,
            "session_id": session_id or self._session_id,
            "user_text": user_content,
            "assistant_text": assistant_content,
            "summary": "",
            "content": json.dumps(
                turn_messages, ensure_ascii=False, separators=(",", ":")
            ),
        }
        self._executor.submit(self._archive_turn, payload)

    def _archive_turn(self, payload: dict[str, Any]) -> None:
        try:
            self._call("turn.archive", payload)
        except RuntimeError as error:
            logger.warning("Memory Palace turn archival failed: %s", error)

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

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)


def _id_parameters(field: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {field: {"type": "string"}},
        "required": [field],
    }


def _current_turn_messages(
    messages: list[dict[str, Any]] | None,
    user_content: str,
    assistant_content: str,
) -> list[dict[str, Any]]:
    if not messages:
        return [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user" and message.get("content") == user_content:
            start = index
            break
    return messages[start:]


def register(ctx: Any) -> None:
    ctx.register_memory_provider(MemoryPalaceMemoryProvider())

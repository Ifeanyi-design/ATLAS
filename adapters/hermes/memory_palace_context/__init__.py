"""Hermes ContextEngine adapter for the Rust Memory Palace daemon."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from agent.context_engine import ContextEngine

from .client import MemoryPalaceClient

logger = logging.getLogger(__name__)


def _binary_path(hermes_home: Path) -> Path | None:
    configured = os.environ.get("MEMORY_PALACE_BINARY", "").strip()
    if configured:
        return Path(configured)
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


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _message_text(message: dict[str, Any] | None) -> str:
    if not message:
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _ensure_daemon(
    client: MemoryPalaceClient, binary: Path, palace_home: Path
) -> None:
    try:
        client.call("health")
        return
    except RuntimeError:
        pass
    log_directory = palace_home / "log"
    log_directory.mkdir(parents=True, exist_ok=True)
    with (log_directory / "daemon.log").open("ab") as log_file:
        subprocess.Popen(
            [str(binary), "--home", str(palace_home), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    last_error: RuntimeError | None = None
    for _ in range(30):
        try:
            client.call("health")
            return
        except RuntimeError as error:
            last_error = error
            time.sleep(0.1)
    raise RuntimeError(
        f"Memory Palace daemon did not start; see {log_directory / 'daemon.log'}"
    ) from last_error


class MemoryPalaceContextEngine(ContextEngine):
    """Thin lifecycle adapter; selection and archival stay in Rust."""

    threshold_percent = 0.75
    protect_first_n = 0
    protect_last_n = 0
    emit_automatic_compaction_status = False

    def __init__(self) -> None:
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.threshold_tokens = 0
        self.context_length = 0
        self.compression_count = 0
        self._client: MemoryPalaceClient | None = None
        self._project = "default"
        self._session_id = ""
        self.trigger_tokens = _positive_env_int("MEMORY_PALACE_TRIGGER_TOKENS", 24_000)
        self.target_dynamic_tokens = _positive_env_int(
            "MEMORY_PALACE_TARGET_DYNAMIC_TOKENS", 8_000
        )
        self.max_decision_tokens = _positive_env_int(
            "MEMORY_PALACE_MAX_DECISION_TOKENS", 2_000
        )
        self.max_retrieved_turn_tokens = _positive_env_int(
            "MEMORY_PALACE_MAX_RETRIEVED_TURN_TOKENS", 2_500
        )
        self.min_tool_result_chars = _positive_env_int(
            "MEMORY_PALACE_MIN_TOOL_RESULT_CHARS", 4_096
        )

    @property
    def name(self) -> str:
        return "memory-palace"

    def __deepcopy__(self, memo: dict[int, Any]) -> "MemoryPalaceContextEngine":
        duplicate = type(self)()
        for field in (
            "trigger_tokens",
            "target_dynamic_tokens",
            "max_decision_tokens",
            "max_retrieved_turn_tokens",
            "min_tool_result_chars",
        ):
            setattr(duplicate, field, getattr(self, field))
        return duplicate

    def update_from_response(self, usage: dict[str, Any]) -> None:
        self.last_prompt_tokens = int(
            usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
        )
        self.last_completion_tokens = int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
        self.last_total_tokens = int(
            usage.get(
                "total_tokens", self.last_prompt_tokens + self.last_completion_tokens
            )
            or 0
        )

    def should_compress(self, prompt_tokens: int = None) -> bool:
        current = self.last_prompt_tokens if prompt_tokens is None else prompt_tokens
        return bool(current and current >= self.trigger_tokens)

    def compress(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int | None = None,
        focus_topic: str | None = None,
        force: bool = False,
        memory_context: str = "",
    ) -> list[dict[str, Any]]:
        try:
            self._call(
                "checkpoint.archive",
                {
                    "project": self._project,
                    "session_id": self._session_id,
                    "content": json.dumps(
                        messages, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            )
        except RuntimeError as error:
            logger.error("Memory Palace compression checkpoint failed closed: %s", error)
            return messages
        selected = self._select(
            messages,
            query=focus_topic or "",
            trigger_tokens=1 if force else self.trigger_tokens,
        )
        if selected is not messages:
            self.compression_count += 1
        return selected

    def select_context(
        self,
        request_messages: list[dict[str, Any]],
        *,
        conversation_messages: list[dict[str, Any]] = None,
        incoming_message: dict[str, Any] = None,
        budget_tokens: int = 0,
    ) -> list[dict[str, Any]] | None:
        selected = self._select(
            request_messages,
            query=_message_text(incoming_message) if incoming_message else "",
        )
        return None if selected is request_messages else selected

    def prune_tool_results_only(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        try:
            result = self._call(
                "context.prune",
                {
                    "project": self._project,
                    "messages": messages,
                    "min_result_chars": self.min_tool_result_chars,
                },
            )
            return result["messages"], int(result["pruned"])
        except (KeyError, TypeError, RuntimeError) as error:
            logger.warning("Memory Palace tool pruning failed open: %s", error)
            return messages, 0

    def on_session_start(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = Path(kwargs["hermes_home"])
        palace_home = hermes_home / "memory-palace"
        binary = _binary_path(hermes_home)
        self._session_id = session_id
        self._project = _project_name(kwargs.get("project"))
        if binary is None:
            logger.warning("Memory Palace context engine unavailable: binary not found")
            return
        client = MemoryPalaceClient(palace_home / "run" / "memory-palace.sock")
        try:
            _ensure_daemon(client, binary, palace_home)
            self._client = client
            self._call("project.resolve", {"name": self._project})
        except RuntimeError as error:
            logger.warning("Memory Palace context engine starts fail-open: %s", error)
            self._client = None

    def on_session_end(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> None:
        self._session_id = ""

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self._session_id = ""

    def _select(
        self,
        messages: list[dict[str, Any]],
        *,
        query: str = "",
        trigger_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            result = self._call(
                "context.select",
                {
                    "project": self._project,
                    "messages": messages,
                    "query": query,
                    "trigger_tokens": trigger_tokens or self.trigger_tokens,
                    "target_dynamic_tokens": self.target_dynamic_tokens,
                    "max_decision_tokens": self.max_decision_tokens,
                    "max_retrieved_turn_tokens": self.max_retrieved_turn_tokens,
                },
            )
            return result["messages"] if result.get("selected") else messages
        except (KeyError, TypeError, RuntimeError) as error:
            logger.warning("Memory Palace context selection failed open: %s", error)
            return messages

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._client is None:
            raise RuntimeError("Memory Palace context engine is not initialized")
        return self._client.call(method, params)


def register(ctx: Any) -> None:
    ctx.register_context_engine(MemoryPalaceContextEngine())

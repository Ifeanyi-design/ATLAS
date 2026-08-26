from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from typing import Any

ADAPTER_PARENT = Path(__file__).resolve().parents[1] / "adapters" / "hermes"
sys.path.insert(0, str(ADAPTER_PARENT))

agent = types.ModuleType("agent")
memory_provider = types.ModuleType("agent.memory_provider")
memory_provider.MemoryProvider = type("MemoryProvider", (), {})
sys.modules.setdefault("agent", agent)
sys.modules.setdefault("agent.memory_provider", memory_provider)

from memory_palace import (  # noqa: E402
    MemoryPalaceMemoryProvider,
    _current_turn_messages,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, params or {}))
        return {"method": method}


class MemoryPalaceProviderTests(unittest.TestCase):
    def test_current_turn_slice_keeps_active_tool_sequence(self) -> None:
        messages = [
            {"role": "user", "content": "old task"},
            {"role": "assistant", "content": "old response"},
            {"role": "user", "content": "new task"},
            {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        selected = _current_turn_messages(messages, "new task", "done")
        self.assertEqual(selected, messages[2:])

    def test_tools_route_to_project_scoped_daemon_methods(self) -> None:
        provider = MemoryPalaceMemoryProvider()
        client = FakeClient()
        provider._client = client
        provider._project = "project-a"
        result = json.loads(
            provider.handle_tool_call(
                "memory_palace_edit_decision",
                {"decision_id": "decision-1", "reason": "updated"},
            )
        )
        self.assertEqual(result, {"method": "memory.edit_decision"})
        self.assertEqual(
            client.calls[-1],
            (
                "memory.edit_decision",
                {
                    "decision_id": "decision-1",
                    "reason": "updated",
                    "project": "project-a",
                },
            ),
        )
        provider.shutdown()

    def test_sync_turn_dispatches_only_the_completed_turn(self) -> None:
        provider = MemoryPalaceMemoryProvider()
        client = FakeClient()
        provider._client = client
        provider._project = "project-a"
        provider._session_id = "session-a"
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": "current answer"},
        ]
        provider.sync_turn("current", "current answer", messages=messages)
        provider.shutdown()
        method, payload = client.calls[-1]
        self.assertEqual(method, "turn.archive")
        self.assertEqual(json.loads(payload["content"]), messages[2:])
        self.assertEqual(payload["session_id"], "session-a")


if __name__ == "__main__":
    unittest.main()

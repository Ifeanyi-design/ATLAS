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
context_engine = types.ModuleType("agent.context_engine")
context_engine.ContextEngine = type(
    "ContextEngine",
    (),
    {"on_session_reset": lambda self: None},
)
sys.modules.setdefault("agent", agent)
sys.modules.setdefault("agent.memory_provider", memory_provider)
sys.modules.setdefault("agent.context_engine", context_engine)

from memory_palace import MemoryPalaceMemoryProvider, _current_turn_messages  # noqa: E402
from memory_palace_context import MemoryPalaceContextEngine  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, params or {}))
        return {"method": method}


class FailingClient:
    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        raise RuntimeError("daemon unavailable")


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
        self.assertEqual(method, "turn.ingest")
        self.assertEqual(payload["messages"], messages[2:])
        self.assertEqual(payload["session_id"], "session-a")

    def test_prefetch_requests_a_bounded_rust_capsule(self) -> None:
        provider = MemoryPalaceMemoryProvider()
        client = FakeClient()
        provider._client = client
        provider._project = "project-a"
        self.assertEqual(provider.prefetch("webhook retry"), "")
        self.assertEqual(
            client.calls[-1],
            (
                "memory.capsule",
                {
                    "project": "project-a",
                    "query": "webhook retry",
                    "max_chars": 8_000,
                },
            ),
        )
        provider.shutdown()

    def test_context_selection_and_pruning_fail_open(self) -> None:
        messages = [
            {"role": "system", "content": "harness"},
            {"role": "user", "content": "current"},
        ]
        engine = MemoryPalaceContextEngine()
        engine._client = FailingClient()
        self.assertIsNone(
            engine.select_context(
                messages,
                incoming_message={"role": "user", "content": "current"},
            )
        )
        pruned, count = engine.prune_tool_results_only(messages)
        self.assertIs(pruned, messages)
        self.assertEqual(count, 0)
        self.assertIs(engine.compress(messages, force=True), messages)

    def test_context_engine_routes_selection_to_rust(self) -> None:
        messages = [
            {"role": "system", "content": "harness"},
            {"role": "user", "content": "current"},
        ]

        class SelectionClient(FakeClient):
            def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
                super().call(method, params)
                return {
                    "selected": True,
                    "messages": [messages[0], {"role": "system", "content": "capsule"}, messages[1]],
                }

        engine = MemoryPalaceContextEngine()
        client = SelectionClient()
        engine._client = client
        engine._project = "project-a"
        selected = engine.select_context(
            messages,
            incoming_message={"role": "user", "content": "current"},
        )
        self.assertEqual(selected[1]["content"], "capsule")
        method, payload = client.calls[-1]
        self.assertEqual(method, "context.select")
        self.assertEqual(payload["project"], "project-a")
        self.assertEqual(payload["query"], "current")

    def test_compression_checkpoints_before_reducing_context(self) -> None:
        messages = [
            {"role": "system", "content": "harness"},
            {"role": "user", "content": "current"},
        ]

        class CompressionClient(FakeClient):
            def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
                self.calls.append((method, params or {}))
                if method == "checkpoint.archive":
                    return {"checkpoint_id": "memory-palace:checkpoint:sha256:test"}
                return {
                    "selected": True,
                    "messages": [messages[0], {"role": "user", "content": "reduced"}],
                }

        engine = MemoryPalaceContextEngine()
        client = CompressionClient()
        engine._client = client
        engine._project = "project-a"
        reduced = engine.compress(messages, force=True)
        self.assertEqual(reduced[-1]["content"], "reduced")
        self.assertEqual(
            [method for method, _ in client.calls],
            ["checkpoint.archive", "context.select"],
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.extraction import DecisionExtraction, ExtractionError, extract_decision


class IntelligenceError(RuntimeError):
    """Raised when an Atlas intelligence operation cannot complete."""


class DecisionIntelligence(Protocol):
    def extract(self, exchange: str) -> DecisionExtraction: ...

    def embed(self, decision: str, reason: str) -> list[float]: ...

    def update_summary(self, current_summary: str | None, decision: str, reason: str) -> str: ...


class ContextIntelligence(Protocol):
    def embed(self, decision: str, reason: str = "") -> list[float]: ...

    def curate(self, prompt: str, candidates: list[dict[str, Any]], limit: int) -> list[str]: ...

    def detect_conflict(self, prompt: str, candidates: list[dict[str, Any]]) -> dict[str, Any]: ...


class OfflineIntelligence:
    """Deterministic, no-cost local behavior for demos and development.

    It intentionally favors explicit decisions over guessing.  An API key
    transparently upgrades this implementation to semantic model calls.
    """

    _decision_pattern = re.compile(r"(?im)^\s*decision\s*:\s*(.+)$")
    _reason_pattern = re.compile(r"(?im)^\s*reason\s*:\s*(.+)$")
    _design_context_pattern = re.compile(r"(?im)^\s*design\s*context\s*:\s*(\{.+\})\s*$")
    _path_pattern = re.compile(r"(?<!\w)((?:[\w.-]+/)+[\w.-]+(?:\.[\w.-]+)?)")
    _commitment_pattern = re.compile(r"(?i)\b(?:we(?:'ll| will)?|i(?:'ll| will)?|let's)\s+(?:use|keep|store|build|implement|make|choose|avoid|ship)\b")
    _token_pattern = re.compile(r"[a-z0-9_]+")
    _opposition_terms = {"avoid", "dont", "instead", "migrate", "no", "not", "remove", "replace", "switch", "without"}
    _common_terms = {"a", "an", "and", "app", "build", "for", "in", "of", "the", "to", "use", "we", "with"}

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract(self, exchange: str) -> DecisionExtraction:
        decision_match = self._decision_pattern.search(exchange)
        reason_match = self._reason_pattern.search(exchange)
        if decision_match is not None:
            decision = decision_match.group(1).strip()
            reason = reason_match.group(1).strip() if reason_match is not None else "Explicitly recorded for project continuity."
        else:
            committed_lines = [line.strip() for line in exchange.splitlines() if self._commitment_pattern.search(line)]
            if not committed_lines:
                return DecisionExtraction(is_real_decision=False)
            decision = committed_lines[-1]
            reason = "Explicitly committed in the exchange."

        paths = list(dict.fromkeys(path.replace("\\", "/") for path in self._path_pattern.findall(exchange)))
        design_context = None
        design_context_match = self._design_context_pattern.search(exchange)
        if design_context_match is not None:
            try:
                parsed_context = json.loads(design_context_match.group(1))
            except json.JSONDecodeError:
                parsed_context = None
            if isinstance(parsed_context, dict):
                design_context = parsed_context
        return DecisionExtraction(
            is_real_decision=True,
            decision=decision,
            reason=reason,
            affected_files=paths,
            design_context=design_context,
        )

    def _tokens(self, text: str) -> list[str]:
        return self._token_pattern.findall(text.lower())

    def embed(self, decision: str, reason: str = "") -> list[float]:
        dimensions = self.settings.embedding_dimensions
        vector = [0.0] * dimensions
        for token, count in Counter(self._tokens(f"{decision} {reason}")).items():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += count if digest[4] % 2 else -count
        magnitude = math.sqrt(sum(value * value for value in vector))
        return vector if magnitude == 0 else [value / magnitude for value in vector]

    def update_summary(self, current_summary: str | None, decision: str, reason: str) -> str:
        entry = f"- {decision} — {reason}"
        entries = [line for line in (current_summary or "").splitlines() if line.strip()]
        return "\n".join((entries + [entry])[-12:])

    def curate(self, prompt: str, candidates: list[dict[str, Any]], limit: int) -> list[str]:
        query = set(self._tokens(prompt))
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                len(query & set(self._tokens(f"{candidate['decision']} {candidate['reason']}"))),
                candidate["created_at"],
            ),
            reverse=True,
        )
        return [candidate["id"] for candidate in ranked[:limit] if query & set(self._tokens(f"{candidate['decision']} {candidate['reason']}"))]

    def detect_conflict(self, prompt: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        prompt_tokens = set(self._tokens(prompt))
        if not (prompt_tokens & self._opposition_terms):
            return {"has_conflict": False, "new_intent": prompt, "original_decision": None, "original_reason": None, "explanation": None}
        for candidate in candidates:
            decision_tokens = set(self._tokens(candidate["decision"])) - self._common_terms
            if prompt_tokens & decision_tokens:
                return {
                    "has_conflict": True,
                    "new_intent": prompt,
                    "original_decision": candidate["decision"],
                    "original_reason": candidate["reason"],
                    "original_id": candidate["id"],
                    "explanation": "The new request explicitly reverses or replaces a term in this prior decision.",
                }
        return {"has_conflict": False, "new_intent": prompt, "original_decision": None, "original_reason": None, "explanation": None}


class OpenAIIntelligence:
    """Small-model operations used by the Phase 1 capture pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        api_key = self.settings.openai_api_key
        if api_key is None:
            raise IntelligenceError("ATLAS_OPENAI_API_KEY must be configured to capture decisions")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise IntelligenceError("Install the 'openai' package to enable Atlas intelligence calls") from exc

        self.client = OpenAI(api_key=api_key.get_secret_value())

    @classmethod
    def is_configured(cls, settings: Settings | None = None) -> bool:
        configured_settings = settings or get_settings()
        api_key = configured_settings.openai_api_key
        return api_key is not None and bool(api_key.get_secret_value().strip())

    def _text_response(self, model: str, prompt: str) -> str:
        try:
            response = self.client.responses.create(model=model, input=prompt)
        except Exception as exc:
            raise IntelligenceError("model request failed") from exc
        text = getattr(response, "output_text", "")
        if not text:
            raise IntelligenceError("model returned an empty response")
        return text

    def extract(self, exchange: str) -> DecisionExtraction:
        try:
            return extract_decision(
                exchange,
                lambda prompt: self._text_response(self.settings.extraction_model, prompt),
            )
        except ExtractionError as exc:
            raise IntelligenceError("model output could not be validated as a decision") from exc

    def embed(self, decision: str, reason: str) -> list[float]:
        try:
            response = self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=f"Decision: {decision}\nReason: {reason}",
            )
        except Exception as exc:
            raise IntelligenceError("embedding request failed") from exc
        return list(response.data[0].embedding)

    def update_summary(self, current_summary: str | None, decision: str, reason: str) -> str:
        prompt = f"""Update this running engineering project summary with one new durable decision.

Current summary:
{current_summary or "No decisions captured yet."}

New decision: {decision}
Reason: {reason}

Return only a concise factual summary. Preserve relevant prior context; do not mention this instruction."""
        return self._text_response(self.settings.summary_model, prompt).strip()

    def curate(self, prompt: str, candidates: list[dict[str, Any]], limit: int) -> list[str]:
        prompt_text = f"""Select at most {limit} decision ids relevant to the engineering prompt below.
Return only JSON shaped as {{\"ids\": [\"uuid\"]}}. Choose none if nothing is relevant.

Prompt:
{prompt}

Candidates:
{json.dumps(candidates)}"""
        try:
            payload = json.loads(self._text_response(self.settings.summary_model, prompt_text))
            ids = payload.get("ids", [])
            allowed_ids = {candidate["id"] for candidate in candidates}
            return [decision_id for decision_id in ids if decision_id in allowed_ids][:limit]
        except (IntelligenceError, json.JSONDecodeError, AttributeError, TypeError):
            return OfflineIntelligence(self.settings).curate(prompt, candidates, limit)

    def detect_conflict(self, prompt: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        prompt_text = f"""Check whether the new engineering request contradicts one prior decision.
Return only JSON with has_conflict (boolean), original_id (string or null), and explanation (string or null).
Only flag a direct incompatibility, not an implementation detail or compatible refinement.

New request:
{prompt}

Prior decisions:
{json.dumps(candidates)}"""
        fallback = OfflineIntelligence(self.settings).detect_conflict(prompt, candidates)
        try:
            payload = json.loads(self._text_response(self.settings.summary_model, prompt_text))
            candidate_by_id = {candidate["id"]: candidate for candidate in candidates}
            original = candidate_by_id.get(payload.get("original_id"))
            if not payload.get("has_conflict") or original is None:
                return {"has_conflict": False, "new_intent": prompt, "original_decision": None, "original_reason": None, "explanation": None}
            return {
                "has_conflict": True,
                "new_intent": prompt,
                "original_decision": original["decision"],
                "original_reason": original["reason"],
                "original_id": original["id"],
                "explanation": str(payload.get("explanation") or "The new request conflicts with this prior decision."),
            }
        except (IntelligenceError, json.JSONDecodeError, AttributeError, TypeError):
            return fallback

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


EXTRACTION_SYSTEM_PROMPT = """You extract durable engineering decisions from a Codex exchange.

Return only JSON matching this schema:
{
  "is_real_decision": boolean,
  "decision": string | null,
  "reason": string | null,
  "affected_files": string[],
  "design_context": object | null
}

Rules:
- Mark is_real_decision false when the exchange contains only status, exploration, commands, errors, or unresolved options.
- A real decision is a committed engineering choice with a reason or durable implication.
- Keep decision and reason concise, factual, and reusable in a future session.
- affected_files must contain explicit repository paths only.
- design_context is only for structured UI details such as colors, spacing, typography, components, layouts, or asset rules.
"""


class ExtractionError(ValueError):
    """Raised when model output cannot be parsed into the decision schema."""


class DecisionExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_real_decision: bool
    decision: str | None = None
    reason: str | None = None
    affected_files: list[str] = Field(default_factory=list)
    design_context: dict[str, Any] | None = None

    @field_validator("decision", "reason")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("affected_files")
    @classmethod
    def clean_file_paths(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for path in value:
            normalized = path.strip().replace("\\", "/")
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned

    def require_storable_decision(self) -> None:
        if not self.is_real_decision:
            return
        if self.decision is None:
            raise ValueError("real decisions must include a decision")
        if self.reason is None:
            raise ValueError("real decisions must include a reason")


ModelExtractor = Callable[[str], str | dict[str, Any]]


def build_extraction_prompt(exchange: str) -> str:
    return f"{EXTRACTION_SYSTEM_PROMPT}\n\nExchange:\n{exchange.strip()}"


def parse_extraction_response(response: str | dict[str, Any]) -> DecisionExtraction:
    if isinstance(response, str):
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ExtractionError("model response was not valid JSON") from exc
    else:
        payload = response

    try:
        extraction = DecisionExtraction.model_validate(payload)
        extraction.require_storable_decision()
    except (ValidationError, ValueError) as exc:
        raise ExtractionError(str(exc)) from exc

    return extraction


def extract_decision(exchange: str, model_extractor: ModelExtractor, max_attempts: int = 2) -> DecisionExtraction:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    prompt = build_extraction_prompt(exchange)
    last_error: ExtractionError | None = None
    for attempt in range(max_attempts):
        response = model_extractor(prompt)
        try:
            return parse_extraction_response(response)
        except ExtractionError as exc:
            last_error = exc
            prompt = (
                f"{build_extraction_prompt(exchange)}\n\n"
                f"The previous response failed validation: {exc}. Return corrected JSON only."
            )

    assert last_error is not None
    raise last_error

import pytest

from app.extraction import ExtractionError, extract_decision, parse_extraction_response


def test_parse_real_decision() -> None:
    extraction = parse_extraction_response(
        {
            "is_real_decision": True,
            "decision": "Use FastAPI for the Atlas backend.",
            "reason": "It keeps the API surface small and typed.",
            "affected_files": ["backend\\app\\main.py", "backend/app/main.py"],
            "design_context": None,
        }
    )

    assert extraction.decision == "Use FastAPI for the Atlas backend."
    assert extraction.reason == "It keeps the API surface small and typed."
    assert extraction.affected_files == ["backend/app/main.py"]


def test_parse_no_decision_allows_empty_fields() -> None:
    extraction = parse_extraction_response(
        {
            "is_real_decision": False,
            "decision": None,
            "reason": None,
            "affected_files": [],
            "design_context": None,
        }
    )

    assert extraction.is_real_decision is False


def test_real_decision_requires_decision_and_reason() -> None:
    with pytest.raises(ExtractionError):
        parse_extraction_response(
            {
                "is_real_decision": True,
                "decision": "Use SQLAlchemy.",
                "reason": None,
                "affected_files": [],
                "design_context": None,
            }
        )


def test_rejects_malformed_response() -> None:
    with pytest.raises(ExtractionError):
        parse_extraction_response("not json")


def test_parse_design_context() -> None:
    extraction = parse_extraction_response(
        {
            "is_real_decision": True,
            "decision": "Use compact cards for dashboard timeline entries.",
            "reason": "The dashboard is an operational tool and should scan quickly.",
            "affected_files": ["dashboard/src/App.tsx"],
            "design_context": {
                "components": {"timeline_card": {"border_radius": "8px"}},
                "colors": {"surface": "#ffffff"},
            },
        }
    )

    assert extraction.design_context == {
        "components": {"timeline_card": {"border_radius": "8px"}},
        "colors": {"surface": "#ffffff"},
    }


def test_extract_decision_retries_after_invalid_json() -> None:
    responses = iter(
        [
            "not json",
            {
                "is_real_decision": True,
                "decision": "Store design context as structured JSON.",
                "reason": "UI prompts need direct injection without prose summarization.",
                "affected_files": ["backend/app/models.py"],
                "design_context": {"storage": "jsonb"},
            },
        ]
    )

    extraction = extract_decision("exchange", lambda _prompt: next(responses))

    assert extraction.decision == "Store design context as structured JSON."
    assert extraction.design_context == {"storage": "jsonb"}

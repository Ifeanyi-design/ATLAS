from app.core.config import Settings
from app.intelligence import OfflineIntelligence, OpenAIIntelligence


def test_openai_intelligence_is_not_configured_without_a_key() -> None:
    assert OpenAIIntelligence.is_configured(Settings()) is False


def test_offline_intelligence_requires_an_explicit_decision() -> None:
    intelligence = OfflineIntelligence(Settings())

    assert intelligence.extract("We considered PostgreSQL.").is_real_decision is False
    extraction = intelligence.extract("Decision: Use PostgreSQL.\nReason: It supports pgvector.")
    assert extraction.decision == "Use PostgreSQL."
    assert len(intelligence.embed("Use PostgreSQL.")) == 1536


def test_offline_intelligence_captures_explicit_design_context() -> None:
    extraction = OfflineIntelligence(Settings()).extract(
        'Decision: Use a compact dashboard timeline.\n'
        'Reason: Operators need to scan it quickly.\n'
        'Design context: {"colors":{"accent":"#38d9a9"},"spacing":{"card":12}}\n'
        'Affected file: dashboard/app.js'
    )

    assert extraction.design_context == {"colors": {"accent": "#38d9a9"}, "spacing": {"card": 12}}
    assert extraction.affected_files == ["dashboard/app.js"]

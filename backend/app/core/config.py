from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _install_relative_sqlite_url(value: str) -> str:
    """Keep SQLite storage anchored to the Atlas install folder."""
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    raw_path = unquote(value.removeprefix(prefix))
    if raw_path in {"", ":memory:"}:
        return value
    path = Path(raw_path)
    if path.is_absolute():
        return value
    absolute = (PROJECT_ROOT / path).resolve().as_posix()
    return f"{prefix}{absolute}"


class Settings(BaseSettings):
    app_name: str = "Atlas API"
    environment: str = "development"
    storage_mode: Literal["sqlite", "postgres"] = "sqlite"
    database_url: str = "sqlite:///./work/atlas.db"
    migrations_database_url: str | None = None
    project_name: str = PROJECT_ROOT.name
    embedding_dimensions: int = 1536
    api_url: str = "http://127.0.0.1:8000"
    auto_start_api: bool = True
    auto_start_docker: bool = False
    dashboard_pin: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    extraction_model: str = "gpt-5-mini"
    summary_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_prefix="ATLAS_", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        return _install_relative_sqlite_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()

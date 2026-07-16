from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    openai_api_key: SecretStr | None = None
    extraction_model: str = "gpt-5-mini"
    summary_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_prefix="ATLAS_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

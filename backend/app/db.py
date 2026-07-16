from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
_is_sqlite = settings.storage_mode == "sqlite"

# SQLite is the zero-dependency default. PostgreSQL keeps the existing pooled
# pgvector path for shared/team installations.
if _is_sqlite and settings.database_url.startswith("sqlite:///"):
    database_path = settings.database_url.removeprefix("sqlite:///")
    if database_path and database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

engine_options: dict[str, object] = {
    "connect_args": {"check_same_thread": False} if _is_sqlite else {},
}
if not _is_sqlite:
    # A cloud database can suspend while Atlas is idle. Verify a connection
    # before reuse and recycle it before it becomes a long-lived idle socket.
    engine_options.update(pool_pre_ping=True, pool_recycle=240, pool_size=5, max_overflow=2)

engine = create_engine(settings.database_url, **engine_options)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection: object, _: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def initialize_database() -> None:
    """Create the portable local schema; PostgreSQL remains migration-managed."""
    if _is_sqlite:
        # Importing models registers all tables with Base.metadata without
        # creating a circular dependency at module import time.
        from app import models  # noqa: F401

        Base.metadata.create_all(engine)
        existing_columns = {column["name"] for column in inspect(engine).get_columns("conflict_events")}
        compatible_columns = {
            "status": "VARCHAR(20) NOT NULL DEFAULT 'open'",
            "override_reason": "TEXT",
            "overridden_at": "DATETIME",
        }
        with engine.begin() as connection:
            for name, definition in compatible_columns.items():
                if name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE conflict_events ADD COLUMN {name} {definition}"))

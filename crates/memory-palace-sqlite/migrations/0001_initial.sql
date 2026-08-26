CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    hermes_session_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    UNIQUE(project_id, hermes_session_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'superseded', 'retracted')),
    importance INTEGER NOT NULL DEFAULT 3 CHECK(importance BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    superseded_by TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    source_turn_id TEXT
);
CREATE INDEX IF NOT EXISTS decisions_project_status_created
    ON decisions(project_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_files (
    decision_id TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    PRIMARY KEY(decision_id, path)
);
CREATE INDEX IF NOT EXISTS decision_files_path ON decision_files(path);

CREATE TABLE IF NOT EXISTS decision_tags (
    decision_id TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY(decision_id, tag)
);
CREATE INDEX IF NOT EXISTS decision_tags_tag ON decision_tags(tag);

CREATE TABLE IF NOT EXISTS conflicts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    new_intent TEXT NOT NULL,
    explanation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'overridden', 'dismissed')),
    override_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    overridden_at TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    raw_blob_zstd BLOB NOT NULL,
    raw_sha256 TEXT NOT NULL,
    estimated_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tool_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,
    tool_name TEXT NOT NULL,
    invocation_summary TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    raw_blob_zstd BLOB NOT NULL,
    raw_sha256 TEXT NOT NULL,
    estimated_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS checkpoints (
    row_id TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    content_sha256 TEXT NOT NULL,
    raw_blob_zstd BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(project_id, session_id, content_sha256)
);
CREATE INDEX IF NOT EXISTS checkpoints_project_id ON checkpoints(project_id, id);

CREATE VIRTUAL TABLE IF NOT EXISTS decision_search USING fts5(
    decision_id UNINDEXED,
    project_id UNINDEXED,
    decision,
    reason,
    files,
    tags,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_search USING fts5(
    evidence_id UNINDEXED,
    project_id UNINDEXED,
    kind UNINDEXED,
    summary,
    tokenize = 'unicode61'
);

"""initial Atlas schema"""
from alembic import op

revision = "20260715_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
    CREATE TABLE projects (id UUID PRIMARY KEY, name VARCHAR(200) NOT NULL UNIQUE, summary TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE sessions (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE, fresh_session BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE decisions (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE, session_id UUID REFERENCES sessions(id) ON DELETE SET NULL, decision TEXT NOT NULL, reason TEXT NOT NULL, affected_files JSONB NOT NULL DEFAULT '[]'::jsonb, embedding vector(1536), created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE INDEX ix_decisions_project_created_at ON decisions (project_id, created_at);
    CREATE INDEX ix_decisions_embedding_hnsw ON decisions USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
    CREATE TABLE design_contexts (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE, decision_id UUID REFERENCES decisions(id) ON DELETE CASCADE, context JSONB NOT NULL, file_paths JSONB NOT NULL DEFAULT '[]'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE INDEX ix_design_contexts_project_created_at ON design_contexts (project_id, created_at);
    CREATE TABLE conflict_events (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE, decision_id UUID REFERENCES decisions(id) ON DELETE SET NULL, new_intent TEXT NOT NULL, explanation TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE INDEX ix_conflict_events_project_created_at ON conflict_events (project_id, created_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conflict_events, design_contexts, decisions, sessions, projects")

use memory_palace_core::{
    ArchivedToolEvent, ArchivedTurn, Conflict, ConflictId, DELETE_ALL_CONFIRMATION, Decision,
    DecisionId, DecisionPatch, DecisionStatus, DomainError, NewDecision, NewToolEvent, NewTurn,
    Project, ProjectId, SearchHit, ToolEventId, TurnId,
};
use rusqlite::{Connection, OptionalExtension, Transaction, params};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};
use uuid::Uuid;

const MIGRATION_1: &str = include_str!("../migrations/0001_initial.sql");

#[derive(Debug, thiserror::Error)]
pub enum StorageError {
    #[error("database error: {0}")]
    Database(#[from] rusqlite::Error),
    #[error("domain validation failed: {0}")]
    Domain(#[from] DomainError),
    #[error("invalid stored UUID: {0}")]
    InvalidUuid(#[from] uuid::Error),
    #[error("storage lock was poisoned")]
    Poisoned,
    #[error("compression error: {0}")]
    Compression(#[from] std::io::Error),
    #[error("{0} was not found")]
    NotFound(&'static str),
    #[error("archived content failed its SHA-256 integrity check")]
    CorruptArchive,
}

#[derive(Clone)]
pub struct Storage {
    connection: Arc<Mutex<Connection>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DoctorReport {
    pub sqlite_version: String,
    pub journal_mode: String,
    pub foreign_keys: bool,
    pub fts5: bool,
    pub migration_version: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StorageStatus {
    pub projects: i64,
    pub decisions: i64,
    pub turns: i64,
    pub tool_events: i64,
    pub checkpoints: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct EvidenceHit {
    pub id: String,
    pub kind: String,
    pub summary: String,
    pub score: f64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenConflictSummary {
    pub id: ConflictId,
    pub new_intent: String,
    pub explanation: String,
}

impl Storage {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StorageError> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let connection = Connection::open(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        Self::from_connection(connection)
    }

    pub fn open_in_memory() -> Result<Self, StorageError> {
        Self::from_connection(Connection::open_in_memory()?)
    }

    fn from_connection(connection: Connection) -> Result<Self, StorageError> {
        connection.busy_timeout(std::time::Duration::from_secs(5))?;
        connection.execute_batch(
            "PRAGMA foreign_keys = ON;\
             PRAGMA synchronous = NORMAL;",
        )?;
        if !connection.is_autocommit() {
            unreachable!("new SQLite connection unexpectedly has an active transaction");
        }
        let storage = Self {
            connection: Arc::new(Mutex::new(connection)),
        };
        storage.migrate()?;
        Ok(storage)
    }

    fn lock(&self) -> Result<MutexGuard<'_, Connection>, StorageError> {
        self.connection.lock().map_err(|_| StorageError::Poisoned)
    }

    fn migrate(&self) -> Result<(), StorageError> {
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        transaction.execute_batch(MIGRATION_1)?;
        transaction.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)",
            [],
        )?;
        transaction.commit()?;
        Ok(())
    }

    pub fn configure_wal(&self) -> Result<String, StorageError> {
        let connection = self.lock()?;
        Ok(connection.query_row("PRAGMA journal_mode = WAL", [], |row| row.get(0))?)
    }

    pub fn doctor(&self) -> Result<DoctorReport, StorageError> {
        let connection = self.lock()?;
        let sqlite_version =
            connection.query_row("SELECT sqlite_version()", [], |row| row.get(0))?;
        let journal_mode = connection.query_row("PRAGMA journal_mode", [], |row| row.get(0))?;
        let foreign_keys: i64 =
            connection.query_row("PRAGMA foreign_keys", [], |row| row.get(0))?;
        let migration_version = connection.query_row(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations",
            [],
            |row| row.get(0),
        )?;
        let fts5 = connection
            .query_row(
                "SELECT 1 FROM pragma_module_list WHERE name = 'fts5'",
                [],
                |_| Ok(true),
            )
            .optional()?
            .unwrap_or(false);
        Ok(DoctorReport {
            sqlite_version,
            journal_mode,
            foreign_keys: foreign_keys == 1,
            fts5,
            migration_version,
        })
    }

    pub fn status(&self) -> Result<StorageStatus, StorageError> {
        let connection = self.lock()?;
        fn count(connection: &Connection, table: &str) -> Result<i64, rusqlite::Error> {
            connection.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                row.get(0)
            })
        }
        Ok(StorageStatus {
            projects: count(&connection, "projects")?,
            decisions: count(&connection, "decisions")?,
            turns: count(&connection, "turns")?,
            tool_events: count(&connection, "tool_events")?,
            checkpoints: count(&connection, "checkpoints")?,
        })
    }

    pub fn resolve_project(&self, name: &str) -> Result<Project, StorageError> {
        let name = name.trim();
        if name.is_empty() {
            return Err(DomainError::EmptyField {
                field: "project name",
            }
            .into());
        }
        let connection = self.lock()?;
        let id = ProjectId::new();
        connection.execute(
            "INSERT INTO projects(id, name) VALUES (?1, ?2) ON CONFLICT(name) DO NOTHING",
            params![id.to_string(), name],
        )?;
        connection
            .query_row(
                "SELECT id, name, summary, created_at, updated_at FROM projects WHERE name = ?1",
                [name],
                map_project,
            )
            .map_err(StorageError::from)
    }

    pub fn log_decision(&self, new: &NewDecision) -> Result<Decision, StorageError> {
        new.validate()?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        let session_id = ensure_session(&transaction, &new.project_id, new.session_id.as_deref())?;
        let id = DecisionId::new();
        transaction.execute(
            "INSERT INTO decisions(
                id, project_id, session_id, decision, reason, importance, source_turn_id
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                id.to_string(),
                new.project_id.to_string(),
                session_id,
                new.decision.trim(),
                new.reason.trim(),
                new.importance,
                new.source_turn_id,
            ],
        )?;

        let files = normalized(&new.affected_files);
        let tags = normalized(&new.tags);
        for path in &files {
            transaction.execute(
                "INSERT INTO decision_files(decision_id, path) VALUES (?1, ?2)",
                params![id.to_string(), path],
            )?;
        }
        for tag in &tags {
            transaction.execute(
                "INSERT INTO decision_tags(decision_id, tag) VALUES (?1, ?2)",
                params![id.to_string(), tag],
            )?;
        }
        transaction.execute(
            "INSERT INTO decision_search(decision_id, project_id, decision, reason, files, tags)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                id.to_string(),
                new.project_id.to_string(),
                new.decision.trim(),
                new.reason.trim(),
                files.join(" "),
                tags.join(" "),
            ],
        )?;
        transaction.commit()?;
        drop(connection);
        self.get_decision(&new.project_id, &id)?
            .ok_or(rusqlite::Error::QueryReturnedNoRows.into())
    }

    pub fn get_decision(
        &self,
        project_id: &ProjectId,
        decision_id: &DecisionId,
    ) -> Result<Option<Decision>, StorageError> {
        let connection = self.lock()?;
        load_decision(&connection, project_id, decision_id)
    }

    pub fn search_decisions(
        &self,
        project_id: &ProjectId,
        query: &str,
        limit: usize,
    ) -> Result<Vec<SearchHit>, StorageError> {
        let fts_query = safe_fts_query(query);
        if fts_query.is_empty() || limit == 0 {
            return Ok(Vec::new());
        }
        let connection = self.lock()?;
        let mut statement = connection.prepare(
            "SELECT d.id, -bm25(decision_search, 1.0, 2.0, 1.2, 1.2) + (d.importance * 0.05) AS score
             FROM decision_search
             JOIN decisions d ON d.id = decision_search.decision_id
             WHERE decision_search MATCH ?1
               AND decision_search.project_id = ?2
               AND d.status = 'active'
             ORDER BY score DESC, d.created_at DESC, d.id ASC
             LIMIT ?3",
        )?;
        let rows = statement.query_map(
            params![fts_query, project_id.to_string(), limit.min(100) as i64],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?)),
        )?;
        let scored_ids: Result<Vec<_>, _> = rows.collect();
        let scored_ids = scored_ids?;
        drop(statement);
        let mut hits = Vec::with_capacity(scored_ids.len());
        for (id, score) in scored_ids {
            let id = DecisionId(Uuid::parse_str(&id)?);
            if let Some(decision) = load_decision(&connection, project_id, &id)? {
                hits.push(SearchHit { decision, score });
            }
        }
        Ok(hits)
    }

    pub fn search_evidence(
        &self,
        project_id: &ProjectId,
        query: &str,
        limit: usize,
    ) -> Result<Vec<EvidenceHit>, StorageError> {
        let fts_query = safe_fts_query(query);
        if fts_query.is_empty() || limit == 0 {
            return Ok(Vec::new());
        }
        let connection = self.lock()?;
        let mut statement = connection.prepare(
            "SELECT evidence_id, kind, summary, -bm25(evidence_search) AS score
             FROM evidence_search
             WHERE evidence_search MATCH ?1 AND project_id = ?2
             ORDER BY score DESC, evidence_id ASC
             LIMIT ?3",
        )?;
        let rows = statement.query_map(
            params![fts_query, project_id.to_string(), limit.min(100) as i64],
            |row| {
                Ok(EvidenceHit {
                    id: row.get(0)?,
                    kind: row.get(1)?,
                    summary: row.get(2)?,
                    score: row.get(3)?,
                })
            },
        )?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn open_conflicts(
        &self,
        project_id: &ProjectId,
        limit: usize,
    ) -> Result<Vec<OpenConflictSummary>, StorageError> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        let connection = self.lock()?;
        let mut statement = connection.prepare(
            "SELECT id, new_intent, explanation FROM conflicts
             WHERE project_id = ?1 AND status = 'open'
             ORDER BY created_at DESC, id ASC LIMIT ?2",
        )?;
        let rows = statement.query_map(
            params![project_id.to_string(), limit.min(100) as i64],
            |row| {
                let id: String = row.get(0)?;
                Ok((id, row.get(1)?, row.get(2)?))
            },
        )?;
        rows.map(|row| {
            let (id, new_intent, explanation): (String, String, String) = row?;
            Ok(OpenConflictSummary {
                id: ConflictId(Uuid::parse_str(&id)?),
                new_intent,
                explanation,
            })
        })
        .collect()
    }

    pub fn edit_decision(
        &self,
        project_id: &ProjectId,
        decision_id: &DecisionId,
        patch: &DecisionPatch,
    ) -> Result<Decision, StorageError> {
        patch.validate()?;
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        let existing = load_decision(&transaction, project_id, decision_id)?
            .ok_or(StorageError::NotFound("decision"))?;
        let decision = patch
            .decision
            .as_deref()
            .map(str::trim)
            .unwrap_or(&existing.decision);
        let reason = patch
            .reason
            .as_deref()
            .map(str::trim)
            .unwrap_or(&existing.reason);
        let importance = patch.importance.unwrap_or(existing.importance);
        let files = patch
            .affected_files
            .as_ref()
            .map(|values| normalized(values))
            .unwrap_or(existing.affected_files);
        let tags = patch
            .tags
            .as_ref()
            .map(|values| normalized(values))
            .unwrap_or(existing.tags);

        transaction.execute(
            "UPDATE decisions
             SET decision = ?1, reason = ?2, importance = ?3,
                 updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = ?4 AND project_id = ?5",
            params![
                decision,
                reason,
                importance,
                decision_id.to_string(),
                project_id.to_string()
            ],
        )?;
        if patch.affected_files.is_some() {
            transaction.execute(
                "DELETE FROM decision_files WHERE decision_id = ?1",
                [decision_id.to_string()],
            )?;
            for path in &files {
                transaction.execute(
                    "INSERT INTO decision_files(decision_id, path) VALUES (?1, ?2)",
                    params![decision_id.to_string(), path],
                )?;
            }
        }
        if patch.tags.is_some() {
            transaction.execute(
                "DELETE FROM decision_tags WHERE decision_id = ?1",
                [decision_id.to_string()],
            )?;
            for tag in &tags {
                transaction.execute(
                    "INSERT INTO decision_tags(decision_id, tag) VALUES (?1, ?2)",
                    params![decision_id.to_string(), tag],
                )?;
            }
        }
        replace_decision_fts(
            &transaction,
            decision_id,
            project_id,
            decision,
            reason,
            &files,
            &tags,
        )?;
        transaction.commit()?;
        drop(connection);
        self.get_decision(project_id, decision_id)?
            .ok_or(StorageError::NotFound("decision"))
    }

    pub fn remove_decision(
        &self,
        project_id: &ProjectId,
        decision_id: &DecisionId,
    ) -> Result<bool, StorageError> {
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        transaction.execute(
            "DELETE FROM decision_search WHERE decision_id = ?1 AND project_id = ?2",
            params![decision_id.to_string(), project_id.to_string()],
        )?;
        let removed = transaction.execute(
            "DELETE FROM decisions WHERE id = ?1 AND project_id = ?2",
            params![decision_id.to_string(), project_id.to_string()],
        )?;
        transaction.commit()?;
        Ok(removed == 1)
    }

    pub fn remove_all_project_memory(
        &self,
        project_id: &ProjectId,
        confirmation: &str,
    ) -> Result<(), StorageError> {
        if confirmation != DELETE_ALL_CONFIRMATION {
            return Err(DomainError::EmptyField {
                field: "exact deletion confirmation",
            }
            .into());
        }
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        transaction.execute(
            "DELETE FROM decision_search WHERE project_id = ?1",
            [project_id.to_string()],
        )?;
        transaction.execute(
            "DELETE FROM evidence_search WHERE project_id = ?1",
            [project_id.to_string()],
        )?;
        for table in [
            "conflicts",
            "tool_events",
            "turns",
            "checkpoints",
            "decisions",
            "sessions",
        ] {
            transaction.execute(
                &format!("DELETE FROM {table} WHERE project_id = ?1"),
                [project_id.to_string()],
            )?;
        }
        transaction.execute(
            "UPDATE projects SET summary = '', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?1",
            [project_id.to_string()],
        )?;
        transaction.commit()?;
        Ok(())
    }

    pub fn archive_turn(&self, new: &NewTurn) -> Result<ArchivedTurn, StorageError> {
        new.validate()?;
        let summary = if new.summary.trim().is_empty() {
            compact_summary(&new.user_text, &new.assistant_text)
        } else {
            new.summary.trim().to_owned()
        };
        let estimated_tokens = estimated_tokens(new.estimated_tokens, new.raw.len());
        let digest = sha256(&new.raw);
        let compressed = zstd::stream::encode_all(new.raw.as_slice(), 3)?;
        let id = TurnId::new();
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        let session_id = ensure_session(&transaction, &new.project_id, new.session_id.as_deref())?;
        transaction.execute(
            "INSERT INTO turns(
                id, project_id, session_id, user_text, assistant_text, summary,
                raw_blob_zstd, raw_sha256, estimated_tokens
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                id.to_string(),
                new.project_id.to_string(),
                session_id,
                new.user_text,
                new.assistant_text,
                summary,
                compressed,
                digest,
                estimated_tokens
            ],
        )?;
        transaction.execute(
            "INSERT INTO evidence_search(evidence_id, project_id, kind, summary)
             VALUES (?1, ?2, 'turn', ?3)",
            params![id.to_string(), new.project_id.to_string(), summary],
        )?;
        transaction.commit()?;
        drop(connection);
        self.get_turn(&new.project_id, &id)?
            .ok_or(StorageError::NotFound("turn"))
    }

    pub fn get_turn(
        &self,
        project_id: &ProjectId,
        turn_id: &TurnId,
    ) -> Result<Option<ArchivedTurn>, StorageError> {
        let connection = self.lock()?;
        load_turn(&connection, project_id, turn_id)
    }

    pub fn recover_turn(
        &self,
        project_id: &ProjectId,
        turn_id: &TurnId,
    ) -> Result<Option<Vec<u8>>, StorageError> {
        let connection = self.lock()?;
        let row: Option<(Vec<u8>, String)> = connection
            .query_row(
                "SELECT raw_blob_zstd, raw_sha256 FROM turns WHERE project_id = ?1 AND id = ?2",
                params![project_id.to_string(), turn_id.to_string()],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        row.map(|(compressed, digest)| decode_verified(&compressed, &digest))
            .transpose()
    }

    pub fn archive_tool_event(
        &self,
        new: &NewToolEvent,
    ) -> Result<ArchivedToolEvent, StorageError> {
        new.validate()?;
        let estimated_tokens = estimated_tokens(new.estimated_tokens, new.raw.len());
        let digest = sha256(&new.raw);
        let compressed = zstd::stream::encode_all(new.raw.as_slice(), 3)?;
        let id = ToolEventId::new();
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        if let Some(turn_id) = &new.turn_id {
            let exists: bool = transaction.query_row(
                "SELECT EXISTS(SELECT 1 FROM turns WHERE id = ?1 AND project_id = ?2)",
                params![turn_id.to_string(), new.project_id.to_string()],
                |row| row.get(0),
            )?;
            if !exists {
                return Err(StorageError::NotFound("turn"));
            }
        }
        transaction.execute(
            "INSERT INTO tool_events(
                id, project_id, turn_id, tool_name, invocation_summary, result_summary,
                raw_blob_zstd, raw_sha256, estimated_tokens
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                id.to_string(),
                new.project_id.to_string(),
                new.turn_id.as_ref().map(ToString::to_string),
                new.tool_name.trim(),
                new.invocation_summary,
                new.result_summary,
                compressed,
                digest,
                estimated_tokens
            ],
        )?;
        transaction.execute(
            "INSERT INTO evidence_search(evidence_id, project_id, kind, summary)
             VALUES (?1, ?2, 'tool_event', ?3)",
            params![
                id.to_string(),
                new.project_id.to_string(),
                format!("{} {}", new.invocation_summary, new.result_summary)
            ],
        )?;
        transaction.commit()?;
        drop(connection);
        self.get_tool_event(&new.project_id, &id)?
            .ok_or(StorageError::NotFound("tool event"))
    }

    pub fn get_tool_event(
        &self,
        project_id: &ProjectId,
        event_id: &ToolEventId,
    ) -> Result<Option<ArchivedToolEvent>, StorageError> {
        let connection = self.lock()?;
        load_tool_event(&connection, project_id, event_id)
    }

    pub fn find_tool_event_by_content(
        &self,
        project_id: &ProjectId,
        content: &[u8],
    ) -> Result<Option<ArchivedToolEvent>, StorageError> {
        let digest = sha256(content);
        let connection = self.lock()?;
        let id: Option<String> = connection
            .query_row(
                "SELECT id FROM tool_events
                 WHERE project_id = ?1 AND raw_sha256 = ?2
                 ORDER BY created_at ASC, id ASC LIMIT 1",
                params![project_id.to_string(), digest],
                |row| row.get(0),
            )
            .optional()?;
        id.map(|value| {
            let id = ToolEventId(Uuid::parse_str(&value)?);
            load_tool_event(&connection, project_id, &id)?
                .ok_or(StorageError::NotFound("tool event"))
        })
        .transpose()
    }

    pub fn recover_tool_event(
        &self,
        project_id: &ProjectId,
        event_id: &ToolEventId,
    ) -> Result<Option<Vec<u8>>, StorageError> {
        let connection = self.lock()?;
        let row: Option<(Vec<u8>, String)> = connection
            .query_row(
                "SELECT raw_blob_zstd, raw_sha256 FROM tool_events WHERE project_id = ?1 AND id = ?2",
                params![project_id.to_string(), event_id.to_string()],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        row.map(|(compressed, digest)| decode_verified(&compressed, &digest))
            .transpose()
    }

    pub fn archive_checkpoint(
        &self,
        project_id: &ProjectId,
        session_id: Option<&str>,
        content: &[u8],
    ) -> Result<String, StorageError> {
        let digest = sha256(content);
        let id = format!("memory-palace:checkpoint:sha256:{digest}");
        let compressed = zstd::stream::encode_all(content, 3)?;
        let mut connection = self.lock()?;
        // Ordinary writes use WAL + NORMAL for latency. A pre-compression
        // checkpoint is the fail-closed evidence boundary, so make this one
        // transaction FULL-durable before acknowledging it.
        connection.pragma_update(None, "synchronous", "FULL")?;
        let write_result = (|| -> Result<(), StorageError> {
            let transaction = connection.transaction()?;
            let session_id = ensure_session(&transaction, project_id, session_id)?;
            transaction.execute(
                "INSERT INTO checkpoints(row_id, id, project_id, session_id, content_sha256, raw_blob_zstd)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                 ON CONFLICT(project_id, session_id, content_sha256) DO NOTHING",
                params![
                    Uuid::now_v7().to_string(),
                    id,
                    project_id.to_string(),
                    session_id,
                    digest,
                    compressed
                ],
            )?;
            transaction.commit()?;
            Ok(())
        })();
        let reset_result = connection.pragma_update(None, "synchronous", "NORMAL");
        write_result?;
        reset_result?;
        Ok(id)
    }

    pub fn recover_checkpoint(
        &self,
        project_id: &ProjectId,
        id: &str,
    ) -> Result<Option<Vec<u8>>, StorageError> {
        let connection = self.lock()?;
        let row: Option<(Vec<u8>, String)> = connection
            .query_row(
                "SELECT raw_blob_zstd, content_sha256 FROM checkpoints
                 WHERE project_id = ?1 AND id = ?2 LIMIT 1",
                params![project_id.to_string(), id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        row.map(|(compressed, digest)| decode_verified(&compressed, &digest))
            .transpose()
    }

    pub fn record_conflict(
        &self,
        project_id: &ProjectId,
        decision_id: Option<&DecisionId>,
        new_intent: &str,
        explanation: &str,
    ) -> Result<Conflict, StorageError> {
        if new_intent.trim().is_empty() {
            return Err(DomainError::EmptyField {
                field: "new intent",
            }
            .into());
        }
        if explanation.trim().is_empty() {
            return Err(DomainError::EmptyField {
                field: "explanation",
            }
            .into());
        }
        let mut connection = self.lock()?;
        let transaction = connection.transaction()?;
        if let Some(decision_id) = decision_id {
            let exists: bool = transaction.query_row(
                "SELECT EXISTS(SELECT 1 FROM decisions WHERE id = ?1 AND project_id = ?2)",
                params![decision_id.to_string(), project_id.to_string()],
                |row| row.get(0),
            )?;
            if !exists {
                return Err(StorageError::NotFound("decision"));
            }
        }
        let id = ConflictId::new();
        transaction.execute(
            "INSERT INTO conflicts(id, project_id, decision_id, new_intent, explanation)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                id.to_string(),
                project_id.to_string(),
                decision_id.map(ToString::to_string),
                new_intent.trim(),
                explanation.trim()
            ],
        )?;
        transaction.commit()?;
        drop(connection);
        self.get_conflict(project_id, &id)?
            .ok_or(StorageError::NotFound("conflict"))
    }

    pub fn override_conflict(
        &self,
        project_id: &ProjectId,
        conflict_id: &ConflictId,
        reason: &str,
    ) -> Result<Conflict, StorageError> {
        if reason.trim().is_empty() {
            return Err(DomainError::EmptyField {
                field: "override reason",
            }
            .into());
        }
        let connection = self.lock()?;
        let updated = connection.execute(
            "UPDATE conflicts
             SET status = 'overridden', override_reason = ?1,
                 overridden_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = ?2 AND project_id = ?3 AND status = 'open'",
            params![
                reason.trim(),
                conflict_id.to_string(),
                project_id.to_string()
            ],
        )?;
        if updated == 0 {
            let existing = load_conflict(&connection, project_id, conflict_id)?;
            return existing.ok_or(StorageError::NotFound("conflict"));
        }
        load_conflict(&connection, project_id, conflict_id)?
            .ok_or(StorageError::NotFound("conflict"))
    }

    pub fn get_conflict(
        &self,
        project_id: &ProjectId,
        conflict_id: &ConflictId,
    ) -> Result<Option<Conflict>, StorageError> {
        let connection = self.lock()?;
        load_conflict(&connection, project_id, conflict_id)
    }
}

fn sha256(content: &[u8]) -> String {
    format!("{:x}", Sha256::digest(content))
}

fn decode_verified(compressed: &[u8], expected_digest: &str) -> Result<Vec<u8>, StorageError> {
    let content = zstd::stream::decode_all(compressed)?;
    if sha256(&content) != expected_digest {
        return Err(StorageError::CorruptArchive);
    }
    Ok(content)
}

fn estimated_tokens(supplied: i64, byte_length: usize) -> i64 {
    if supplied > 0 {
        supplied
    } else {
        byte_length.div_ceil(4) as i64
    }
}

fn compact_summary(user_text: &str, assistant_text: &str) -> String {
    let combined = format!(
        "User: {} Assistant: {}",
        user_text.trim(),
        assistant_text.trim()
    );
    combined.chars().take(512).collect()
}

fn normalized(values: &[String]) -> Vec<String> {
    values
        .iter()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn replace_decision_fts(
    transaction: &Transaction<'_>,
    decision_id: &DecisionId,
    project_id: &ProjectId,
    decision: &str,
    reason: &str,
    files: &[String],
    tags: &[String],
) -> Result<(), rusqlite::Error> {
    transaction.execute(
        "DELETE FROM decision_search WHERE decision_id = ?1 AND project_id = ?2",
        params![decision_id.to_string(), project_id.to_string()],
    )?;
    transaction.execute(
        "INSERT INTO decision_search(decision_id, project_id, decision, reason, files, tags)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![
            decision_id.to_string(),
            project_id.to_string(),
            decision,
            reason,
            files.join(" "),
            tags.join(" ")
        ],
    )?;
    Ok(())
}

fn safe_fts_query(query: &str) -> String {
    query
        .split(|character: char| {
            !character.is_alphanumeric() && character != '_' && character != '-'
        })
        .filter(|term| !term.is_empty())
        .map(|term| format!("\"{}\"*", term.replace('"', "\"\"")))
        .collect::<Vec<_>>()
        .join(" OR ")
}

fn ensure_session(
    transaction: &Transaction<'_>,
    project_id: &ProjectId,
    hermes_session_id: Option<&str>,
) -> Result<Option<String>, rusqlite::Error> {
    let Some(hermes_session_id) = hermes_session_id.filter(|value| !value.trim().is_empty()) else {
        return Ok(None);
    };
    let existing: Option<String> = transaction
        .query_row(
            "SELECT id FROM sessions WHERE project_id = ?1 AND hermes_session_id = ?2",
            params![project_id.to_string(), hermes_session_id],
            |row| row.get(0),
        )
        .optional()?;
    if existing.is_some() {
        return Ok(existing);
    }
    let id = Uuid::now_v7().to_string();
    transaction.execute(
        "INSERT INTO sessions(id, project_id, hermes_session_id) VALUES (?1, ?2, ?3)",
        params![id, project_id.to_string(), hermes_session_id],
    )?;
    Ok(Some(id))
}

fn map_project(row: &rusqlite::Row<'_>) -> Result<Project, rusqlite::Error> {
    let id: String = row.get(0)?;
    Ok(Project {
        id: ProjectId(Uuid::parse_str(&id).map_err(|error| {
            rusqlite::Error::FromSqlConversionFailure(
                0,
                rusqlite::types::Type::Text,
                Box::new(error),
            )
        })?),
        name: row.get(1)?,
        summary: row.get(2)?,
        created_at: row.get(3)?,
        updated_at: row.get(4)?,
    })
}

fn load_decision(
    connection: &Connection,
    project_id: &ProjectId,
    decision_id: &DecisionId,
) -> Result<Option<Decision>, StorageError> {
    type BaseDecision = (
        String,
        Option<String>,
        String,
        String,
        String,
        i64,
        String,
        String,
        Option<String>,
        Option<String>,
    );
    let base: Option<BaseDecision> = connection
        .query_row(
            "SELECT id, session_id, decision, reason, status, importance, created_at, updated_at, superseded_by, source_turn_id
             FROM decisions WHERE id = ?1 AND project_id = ?2",
            params![decision_id.to_string(), project_id.to_string()],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?, row.get(5)?, row.get(6)?, row.get(7)?, row.get(8)?, row.get(9)?)),
        )
        .optional()?;
    let Some((
        id,
        session_id,
        decision,
        reason,
        status,
        importance,
        created_at,
        updated_at,
        superseded_by,
        source_turn_id,
    )) = base
    else {
        return Ok(None);
    };
    let values = |sql: &str| -> Result<Vec<String>, rusqlite::Error> {
        let mut statement = connection.prepare(sql)?;
        statement
            .query_map([&id], |row| row.get(0))?
            .collect::<Result<Vec<_>, _>>()
    };
    let status = match status.as_str() {
        "superseded" => DecisionStatus::Superseded,
        "retracted" => DecisionStatus::Retracted,
        _ => DecisionStatus::Active,
    };
    Ok(Some(Decision {
        id: DecisionId(Uuid::parse_str(&id)?),
        project_id: project_id.clone(),
        session_id,
        decision,
        reason,
        status,
        importance,
        affected_files: values(
            "SELECT path FROM decision_files WHERE decision_id = ?1 ORDER BY path",
        )?,
        tags: values("SELECT tag FROM decision_tags WHERE decision_id = ?1 ORDER BY tag")?,
        created_at,
        updated_at,
        superseded_by: superseded_by
            .map(|value| Uuid::parse_str(&value).map(DecisionId))
            .transpose()?,
        source_turn_id,
    }))
}

fn load_turn(
    connection: &Connection,
    project_id: &ProjectId,
    turn_id: &TurnId,
) -> Result<Option<ArchivedTurn>, StorageError> {
    type Row = (
        String,
        Option<String>,
        String,
        String,
        String,
        String,
        i64,
        String,
    );
    let row: Option<Row> = connection
        .query_row(
            "SELECT id, session_id, user_text, assistant_text, summary, raw_sha256,
                    estimated_tokens, created_at
             FROM turns WHERE project_id = ?1 AND id = ?2",
            params![project_id.to_string(), turn_id.to_string()],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                ))
            },
        )
        .optional()?;
    row.map(
        |(
            id,
            session_id,
            user_text,
            assistant_text,
            summary,
            raw_sha256,
            estimated_tokens,
            created_at,
        )| {
            Ok(ArchivedTurn {
                id: TurnId(Uuid::parse_str(&id)?),
                project_id: project_id.clone(),
                session_id,
                user_text,
                assistant_text,
                summary,
                raw_sha256,
                estimated_tokens,
                created_at,
            })
        },
    )
    .transpose()
}

fn load_tool_event(
    connection: &Connection,
    project_id: &ProjectId,
    event_id: &ToolEventId,
) -> Result<Option<ArchivedToolEvent>, StorageError> {
    type Row = (
        String,
        Option<String>,
        String,
        String,
        String,
        String,
        i64,
        String,
    );
    let row: Option<Row> = connection
        .query_row(
            "SELECT id, turn_id, tool_name, invocation_summary, result_summary,
                    raw_sha256, estimated_tokens, created_at
             FROM tool_events WHERE project_id = ?1 AND id = ?2",
            params![project_id.to_string(), event_id.to_string()],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                ))
            },
        )
        .optional()?;
    row.map(
        |(
            id,
            turn_id,
            tool_name,
            invocation_summary,
            result_summary,
            raw_sha256,
            estimated_tokens,
            created_at,
        )| {
            Ok(ArchivedToolEvent {
                id: ToolEventId(Uuid::parse_str(&id)?),
                project_id: project_id.clone(),
                turn_id: turn_id
                    .map(|value| Uuid::parse_str(&value).map(TurnId))
                    .transpose()?,
                tool_name,
                invocation_summary,
                result_summary,
                raw_sha256,
                estimated_tokens,
                created_at,
            })
        },
    )
    .transpose()
}

fn load_conflict(
    connection: &Connection,
    project_id: &ProjectId,
    conflict_id: &ConflictId,
) -> Result<Option<Conflict>, StorageError> {
    type Row = (
        String,
        Option<String>,
        String,
        String,
        String,
        Option<String>,
        String,
        Option<String>,
    );
    let row: Option<Row> = connection
        .query_row(
            "SELECT id, decision_id, new_intent, explanation, status, override_reason,
                    created_at, overridden_at
             FROM conflicts WHERE project_id = ?1 AND id = ?2",
            params![project_id.to_string(), conflict_id.to_string()],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                ))
            },
        )
        .optional()?;
    row.map(
        |(
            id,
            decision_id,
            new_intent,
            explanation,
            status,
            override_reason,
            created_at,
            overridden_at,
        )| {
            Ok(Conflict {
                id: ConflictId(Uuid::parse_str(&id)?),
                project_id: project_id.clone(),
                decision_id: decision_id
                    .map(|value| Uuid::parse_str(&value).map(DecisionId))
                    .transpose()?,
                new_intent,
                explanation,
                status,
                override_reason,
                created_at,
                overridden_at,
            })
        },
    )
    .transpose()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn decision(project_id: ProjectId, text: &str) -> NewDecision {
        NewDecision {
            project_id,
            session_id: Some("hermes-session-1".into()),
            decision: text.into(),
            reason: "The local path must work without network access.".into(),
            affected_files: vec!["src/storage.rs".into(), "src/storage.rs".into()],
            tags: vec!["storage".into()],
            importance: 4,
            source_turn_id: None,
        }
    }

    #[test]
    fn project_scoped_fts_never_leaks_results() {
        let storage = Storage::open_in_memory().unwrap();
        let first = storage.resolve_project("first").unwrap();
        let second = storage.resolve_project("second").unwrap();
        storage
            .log_decision(&decision(first.id.clone(), "Use SQLite for local storage"))
            .unwrap();
        storage
            .log_decision(&decision(
                second.id.clone(),
                "Use SQLite for a secret project",
            ))
            .unwrap();

        let hits = storage
            .search_decisions(&first.id, "sqlite storage", 10)
            .unwrap();
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].decision.project_id, first.id);
        assert_eq!(hits[0].decision.affected_files, vec!["src/storage.rs"]);
    }

    #[test]
    fn checkpoints_are_idempotent_and_recoverable() {
        let storage = Storage::open_in_memory().unwrap();
        let project = storage.resolve_project("checkpoint-test").unwrap();
        let content = "tool output — 測試".as_bytes();
        let first = storage
            .archive_checkpoint(&project.id, Some("session-1"), content)
            .unwrap();
        let second = storage
            .archive_checkpoint(&project.id, Some("session-1"), content)
            .unwrap();
        assert_eq!(first, second);
        assert_eq!(storage.status().unwrap().checkpoints, 1);
        assert_eq!(
            storage
                .recover_checkpoint(&project.id, &first)
                .unwrap()
                .unwrap(),
            content
        );
    }

    #[test]
    fn doctor_reports_required_sqlite_features() {
        let storage = Storage::open_in_memory().unwrap();
        let report = storage.doctor().unwrap();
        assert!(report.foreign_keys);
        assert!(report.fts5);
        assert_eq!(report.migration_version, 1);
    }

    #[test]
    fn file_database_is_private_to_the_current_user() {
        let path = std::env::temp_dir().join(format!("memory-palace-{}.sqlite3", Uuid::now_v7()));
        let storage = Storage::open(&path).unwrap();
        let mode = std::fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        drop(storage);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn turns_and_tool_events_round_trip_without_cross_project_access() {
        let storage = Storage::open_in_memory().unwrap();
        let project = storage.resolve_project("archive-project").unwrap();
        let other = storage.resolve_project("other-project").unwrap();
        let raw_turn = r#"{"messages":[{"role":"user","content":"compile — 測試"}]}"#.as_bytes();
        let turn = storage
            .archive_turn(&NewTurn {
                project_id: project.id.clone(),
                session_id: Some("session-1".into()),
                user_text: "compile — 測試".into(),
                assistant_text: "running tests".into(),
                summary: "Compiler test investigation".into(),
                raw: raw_turn.to_vec(),
                estimated_tokens: 20,
            })
            .unwrap();
        assert_eq!(
            storage
                .recover_turn(&project.id, &turn.id)
                .unwrap()
                .unwrap(),
            raw_turn
        );
        assert!(storage.recover_turn(&other.id, &turn.id).unwrap().is_none());

        let raw_tool = vec![b'x'; 256 * 1024];
        let event = storage
            .archive_tool_event(&NewToolEvent {
                project_id: project.id.clone(),
                turn_id: Some(turn.id.clone()),
                tool_name: "shell".into(),
                invocation_summary: "cargo test".into(),
                result_summary: "all tests passed".into(),
                raw: raw_tool.clone(),
                estimated_tokens: 65_536,
            })
            .unwrap();
        assert_eq!(
            storage
                .recover_tool_event(&project.id, &event.id)
                .unwrap()
                .unwrap(),
            raw_tool
        );
        assert!(
            storage
                .recover_tool_event(&other.id, &event.id)
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn decision_edits_refresh_fts_and_removal_stays_project_scoped() {
        let storage = Storage::open_in_memory().unwrap();
        let project = storage.resolve_project("edit-project").unwrap();
        let other = storage.resolve_project("other-edit-project").unwrap();
        let original = storage
            .log_decision(&decision(project.id.clone(), "Use the obsolete cache"))
            .unwrap();
        let foreign = storage
            .log_decision(&decision(
                other.id.clone(),
                "Use the obsolete cache elsewhere",
            ))
            .unwrap();

        let edited = storage
            .edit_decision(
                &project.id,
                &original.id,
                &DecisionPatch {
                    decision: Some("Use the quartz cache".into()),
                    reason: Some("It has deterministic invalidation.".into()),
                    affected_files: Some(vec!["src/cache.rs".into()]),
                    tags: Some(vec!["cache".into(), "cache".into()]),
                    importance: Some(5),
                },
            )
            .unwrap();
        assert_eq!(edited.tags, vec!["cache"]);
        assert_eq!(edited.importance, 5);
        assert!(
            storage
                .search_decisions(&project.id, "obsolete", 10)
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            storage
                .search_decisions(&project.id, "quartz invalidation", 10)
                .unwrap()
                .len(),
            1
        );

        assert!(!storage.remove_decision(&project.id, &foreign.id).unwrap());
        assert!(storage.remove_decision(&project.id, &original.id).unwrap());
        assert!(
            storage
                .search_decisions(&project.id, "quartz", 10)
                .unwrap()
                .is_empty()
        );
        assert!(
            storage
                .get_decision(&other.id, &foreign.id)
                .unwrap()
                .is_some()
        );
    }

    #[test]
    fn conflict_overrides_are_scoped_and_auditable() {
        let storage = Storage::open_in_memory().unwrap();
        let project = storage.resolve_project("conflict-project").unwrap();
        let other = storage.resolve_project("other-conflict-project").unwrap();
        let saved = storage
            .log_decision(&decision(project.id.clone(), "Use SQLite locally"))
            .unwrap();
        let conflict = storage
            .record_conflict(
                &project.id,
                Some(&saved.id),
                "Replace SQLite with a remote database",
                "The request changes the authoritative local store.",
            )
            .unwrap();
        assert_eq!(conflict.status, "open");
        assert!(matches!(
            storage.override_conflict(&other.id, &conflict.id, "wrong project"),
            Err(StorageError::NotFound("conflict"))
        ));
        let overridden = storage
            .override_conflict(
                &project.id,
                &conflict.id,
                "The deployment now requires shared storage.",
            )
            .unwrap();
        assert_eq!(overridden.status, "overridden");
        assert_eq!(
            overridden.override_reason.as_deref(),
            Some("The deployment now requires shared storage.")
        );
        assert!(overridden.overridden_at.is_some());
    }

    #[test]
    fn whole_project_removal_requires_exact_confirmation() {
        let storage = Storage::open_in_memory().unwrap();
        let project = storage.resolve_project("delete-project").unwrap();
        let other = storage.resolve_project("keep-project").unwrap();
        storage
            .log_decision(&decision(project.id.clone(), "Delete this decision"))
            .unwrap();
        let kept = storage
            .log_decision(&decision(other.id.clone(), "Keep this decision"))
            .unwrap();
        assert!(
            storage
                .remove_all_project_memory(&project.id, "yes")
                .is_err()
        );
        assert_eq!(
            storage
                .search_decisions(&project.id, "delete decision", 10)
                .unwrap()
                .len(),
            1
        );

        storage
            .remove_all_project_memory(&project.id, DELETE_ALL_CONFIRMATION)
            .unwrap();
        assert!(
            storage
                .search_decisions(&project.id, "delete decision", 10)
                .unwrap()
                .is_empty()
        );
        assert!(storage.get_decision(&other.id, &kept.id).unwrap().is_some());
    }
}

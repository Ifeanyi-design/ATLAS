use memory_palace_core::{
    Decision, DecisionId, DecisionStatus, DomainError, NewDecision, Project, ProjectId, SearchHit,
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

    pub fn archive_checkpoint(
        &self,
        project_id: &ProjectId,
        session_id: Option<&str>,
        content: &[u8],
    ) -> Result<String, StorageError> {
        let digest = format!("{:x}", Sha256::digest(content));
        let id = format!("memory-palace:checkpoint:sha256:{digest}");
        let compressed = zstd::stream::encode_all(content, 3)?;
        let mut connection = self.lock()?;
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
        Ok(id)
    }

    pub fn recover_checkpoint(
        &self,
        project_id: &ProjectId,
        id: &str,
    ) -> Result<Option<Vec<u8>>, StorageError> {
        let connection = self.lock()?;
        let compressed: Option<Vec<u8>> = connection
            .query_row(
                "SELECT raw_blob_zstd FROM checkpoints WHERE project_id = ?1 AND id = ?2 LIMIT 1",
                params![project_id.to_string(), id],
                |row| row.get(0),
            )
            .optional()?;
        compressed
            .map(|value| zstd::stream::decode_all(value.as_slice()).map_err(StorageError::from))
            .transpose()
    }
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
}

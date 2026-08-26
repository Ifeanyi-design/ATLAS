use memory_palace_core::{
    ConflictId, DecisionId, DecisionPatch, NewDecision, NewToolEvent, NewTurn, ToolEventId, TurnId,
};
use memory_palace_protocol::{MAX_FRAME_BYTES, PROTOCOL_VERSION, Request, Response, encode_frame};
use memory_palace_sqlite::{Storage, StorageError};
use serde::Deserialize;
use serde_json::{Value, json};
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::thread;
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum DaemonError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("storage error: {0}")]
    Storage(#[from] StorageError),
    #[error("another Memory Palace daemon is already listening at {0}")]
    AlreadyRunning(String),
    #[error("refusing to replace non-socket path {0}")]
    UnsafeSocketPath(String),
}

pub fn serve(storage: Storage, socket_path: &Path) -> Result<(), DaemonError> {
    if let Some(parent) = socket_path.parent() {
        fs::create_dir_all(parent)?;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o700))?;
    }
    prepare_socket_path(socket_path)?;
    let listener = UnixListener::bind(socket_path)?;
    fs::set_permissions(socket_path, fs::Permissions::from_mode(0o600))?;

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let storage = storage.clone();
                thread::spawn(move || {
                    if let Err(error) = serve_connection(storage, stream) {
                        eprintln!("memory-palace connection error: {error}");
                    }
                });
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

fn prepare_socket_path(path: &Path) -> Result<(), DaemonError> {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return Ok(());
    };
    if !metadata.file_type().is_socket() {
        return Err(DaemonError::UnsafeSocketPath(path.display().to_string()));
    }
    if UnixStream::connect(path).is_ok() {
        return Err(DaemonError::AlreadyRunning(path.display().to_string()));
    }
    fs::remove_file(path)?;
    Ok(())
}

fn serve_connection(storage: Storage, stream: UnixStream) -> Result<(), DaemonError> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;
    loop {
        let Some(frame) = read_frame(&mut reader)? else {
            return Ok(());
        };
        let response = match serde_json::from_slice::<Request>(&frame) {
            Ok(request) => dispatch(&storage, request),
            Err(error) => Response::error("", "INVALID_REQUEST", error.to_string()),
        };
        writer.write_all(&encode_frame(&response).expect("response serialization must succeed"))?;
        writer.flush()?;
    }
}

fn read_frame(reader: &mut BufReader<UnixStream>) -> Result<Option<Vec<u8>>, std::io::Error> {
    let mut frame = Vec::new();
    let mut limited = reader.by_ref().take((MAX_FRAME_BYTES + 1) as u64);
    let bytes = limited.read_until(b'\n', &mut frame)?;
    if bytes == 0 {
        return Ok(None);
    }
    if frame.len() > MAX_FRAME_BYTES {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("frame exceeds {MAX_FRAME_BYTES} bytes"),
        ));
    }
    if frame.last() == Some(&b'\n') {
        frame.pop();
    }
    if frame.last() == Some(&b'\r') {
        frame.pop();
    }
    Ok(Some(frame))
}

pub fn dispatch(storage: &Storage, request: Request) -> Response {
    let id = request.id.clone();
    if let Err(error) = request.validate() {
        return Response::error(id, "INVALID_REQUEST", error.to_string());
    }
    let result = match request.method.as_str() {
        "health" => health(storage),
        "project.resolve" => parse::<ResolveProjectParams>(request.params)
            .and_then(|params| resolve_project(storage, params)),
        "memory.log_decision" => parse::<LogDecisionParams>(request.params)
            .and_then(|params| log_decision(storage, params)),
        "memory.search" => {
            parse::<SearchParams>(request.params).and_then(|params| search(storage, params))
        }
        "memory.get" => parse::<GetDecisionParams>(request.params)
            .and_then(|params| get_decision(storage, params)),
        "memory.edit_decision" => parse::<EditDecisionParams>(request.params)
            .and_then(|params| edit_decision(storage, params)),
        "memory.remove" => parse::<RemoveMemoryParams>(request.params)
            .and_then(|params| remove_memory(storage, params)),
        "conflict.record" => parse::<RecordConflictParams>(request.params)
            .and_then(|params| record_conflict(storage, params)),
        "conflict.override" => parse::<OverrideConflictParams>(request.params)
            .and_then(|params| override_conflict(storage, params)),
        "turn.archive" => parse::<ArchiveTurnParams>(request.params)
            .and_then(|params| archive_turn(storage, params)),
        "turn.get" => {
            parse::<GetTurnParams>(request.params).and_then(|params| get_turn(storage, params))
        }
        "tool_event.archive" => parse::<ArchiveToolEventParams>(request.params)
            .and_then(|params| archive_tool_event(storage, params)),
        "tool_event.get" => parse::<GetToolEventParams>(request.params)
            .and_then(|params| get_tool_event(storage, params)),
        "checkpoint.archive" => {
            parse::<CheckpointParams>(request.params).and_then(|params| checkpoint(storage, params))
        }
        _ => Err(ApiError::new(
            "METHOD_NOT_FOUND",
            format!("unknown method {}", request.method),
        )),
    };
    match result {
        Ok(value) => Response::success(id, value),
        Err(error) => Response::error(id, error.code, error.message),
    }
}

fn health(storage: &Storage) -> Result<Value, ApiError> {
    let report = storage.doctor()?;
    Ok(json!({
        "status": "ok",
        "protocol_version": PROTOCOL_VERSION,
        "sqlite_version": report.sqlite_version,
        "fts5": report.fts5,
    }))
}

#[derive(Deserialize)]
struct ResolveProjectParams {
    name: String,
}

fn resolve_project(storage: &Storage, params: ResolveProjectParams) -> Result<Value, ApiError> {
    Ok(serde_json::to_value(
        storage.resolve_project(&params.name)?,
    )?)
}

#[derive(Deserialize)]
struct LogDecisionParams {
    project: String,
    session_id: Option<String>,
    decision: String,
    reason: String,
    #[serde(default)]
    affected_files: Vec<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default = "default_importance")]
    importance: i64,
    source_turn_id: Option<String>,
}

const fn default_importance() -> i64 {
    3
}

fn log_decision(storage: &Storage, params: LogDecisionParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let decision = storage.log_decision(&NewDecision {
        project_id: project.id,
        session_id: params.session_id,
        decision: params.decision,
        reason: params.reason,
        affected_files: params.affected_files,
        tags: params.tags,
        importance: params.importance,
        source_turn_id: params.source_turn_id,
    })?;
    Ok(serde_json::to_value(decision)?)
}

#[derive(Deserialize)]
struct SearchParams {
    project: String,
    query: String,
    #[serde(default = "default_limit")]
    limit: usize,
}

const fn default_limit() -> usize {
    10
}

fn search(storage: &Storage, params: SearchParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    Ok(serde_json::to_value(storage.search_decisions(
        &project.id,
        &params.query,
        params.limit,
    )?)?)
}

#[derive(Deserialize)]
struct GetDecisionParams {
    project: String,
    decision_id: String,
}

fn get_decision(storage: &Storage, params: GetDecisionParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let id = DecisionId(parse_uuid(&params.decision_id, "decision_id")?);
    let decision = storage
        .get_decision(&project.id, &id)?
        .ok_or_else(|| ApiError::new("NOT_FOUND", "decision was not found"))?;
    Ok(serde_json::to_value(decision)?)
}

#[derive(Deserialize)]
struct EditDecisionParams {
    project: String,
    decision_id: String,
    decision: Option<String>,
    reason: Option<String>,
    affected_files: Option<Vec<String>>,
    tags: Option<Vec<String>>,
    importance: Option<i64>,
}

fn edit_decision(storage: &Storage, params: EditDecisionParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let id = DecisionId(parse_uuid(&params.decision_id, "decision_id")?);
    let decision = storage.edit_decision(
        &project.id,
        &id,
        &DecisionPatch {
            decision: params.decision,
            reason: params.reason,
            affected_files: params.affected_files,
            tags: params.tags,
            importance: params.importance,
        },
    )?;
    Ok(serde_json::to_value(decision)?)
}

#[derive(Deserialize)]
struct RemoveMemoryParams {
    project: String,
    decision_id: Option<String>,
    #[serde(default)]
    delete_all: bool,
    confirmation: Option<String>,
}

fn remove_memory(storage: &Storage, params: RemoveMemoryParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    if params.delete_all {
        let confirmation = params.confirmation.as_deref().unwrap_or_default();
        storage.remove_all_project_memory(&project.id, confirmation)?;
        return Ok(json!({ "status": "removed_all" }));
    }
    let id = params
        .decision_id
        .as_deref()
        .ok_or_else(|| ApiError::new("INVALID_PARAMS", "decision_id is required"))?;
    let id = DecisionId(parse_uuid(id, "decision_id")?);
    let removed = storage.remove_decision(&project.id, &id)?;
    if !removed {
        return Err(ApiError::new("NOT_FOUND", "decision was not found"));
    }
    Ok(json!({ "status": "removed", "decision_id": id }))
}

#[derive(Deserialize)]
struct RecordConflictParams {
    project: String,
    decision_id: Option<String>,
    new_intent: String,
    explanation: String,
}

fn record_conflict(storage: &Storage, params: RecordConflictParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let decision_id = params
        .decision_id
        .as_deref()
        .map(|value| parse_uuid(value, "decision_id").map(DecisionId))
        .transpose()?;
    Ok(serde_json::to_value(storage.record_conflict(
        &project.id,
        decision_id.as_ref(),
        &params.new_intent,
        &params.explanation,
    )?)?)
}

#[derive(Deserialize)]
struct OverrideConflictParams {
    project: String,
    conflict_id: String,
    reason: String,
}

fn override_conflict(storage: &Storage, params: OverrideConflictParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let conflict_id = ConflictId(parse_uuid(&params.conflict_id, "conflict_id")?);
    Ok(serde_json::to_value(storage.override_conflict(
        &project.id,
        &conflict_id,
        &params.reason,
    )?)?)
}

#[derive(Deserialize)]
struct ArchiveTurnParams {
    project: String,
    session_id: Option<String>,
    user_text: String,
    assistant_text: String,
    #[serde(default)]
    summary: String,
    content: String,
    #[serde(default)]
    estimated_tokens: i64,
}

fn archive_turn(storage: &Storage, params: ArchiveTurnParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    Ok(serde_json::to_value(storage.archive_turn(&NewTurn {
        project_id: project.id,
        session_id: params.session_id,
        user_text: params.user_text,
        assistant_text: params.assistant_text,
        summary: params.summary,
        raw: params.content.into_bytes(),
        estimated_tokens: params.estimated_tokens,
    })?)?)
}

#[derive(Deserialize)]
struct GetTurnParams {
    project: String,
    turn_id: String,
}

fn get_turn(storage: &Storage, params: GetTurnParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let turn_id = TurnId(parse_uuid(&params.turn_id, "turn_id")?);
    let record = storage
        .get_turn(&project.id, &turn_id)?
        .ok_or_else(|| ApiError::new("NOT_FOUND", "turn was not found"))?;
    let raw = storage
        .recover_turn(&project.id, &turn_id)?
        .ok_or_else(|| ApiError::new("NOT_FOUND", "turn was not found"))?;
    let content = String::from_utf8(raw)
        .map_err(|_| ApiError::new("INVALID_ARCHIVE", "turn content is not UTF-8"))?;
    Ok(json!({ "record": record, "content": content }))
}

#[derive(Deserialize)]
struct ArchiveToolEventParams {
    project: String,
    turn_id: Option<String>,
    tool_name: String,
    invocation_summary: String,
    result_summary: String,
    content: String,
    #[serde(default)]
    estimated_tokens: i64,
}

fn archive_tool_event(
    storage: &Storage,
    params: ArchiveToolEventParams,
) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let turn_id = params
        .turn_id
        .as_deref()
        .map(|value| parse_uuid(value, "turn_id").map(TurnId))
        .transpose()?;
    Ok(serde_json::to_value(storage.archive_tool_event(
        &NewToolEvent {
            project_id: project.id,
            turn_id,
            tool_name: params.tool_name,
            invocation_summary: params.invocation_summary,
            result_summary: params.result_summary,
            raw: params.content.into_bytes(),
            estimated_tokens: params.estimated_tokens,
        },
    )?)?)
}

#[derive(Deserialize)]
struct GetToolEventParams {
    project: String,
    event_id: String,
}

fn get_tool_event(storage: &Storage, params: GetToolEventParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let event_id = ToolEventId(parse_uuid(&params.event_id, "event_id")?);
    let record = storage
        .get_tool_event(&project.id, &event_id)?
        .ok_or_else(|| ApiError::new("NOT_FOUND", "tool event was not found"))?;
    let raw = storage
        .recover_tool_event(&project.id, &event_id)?
        .ok_or_else(|| ApiError::new("NOT_FOUND", "tool event was not found"))?;
    let content = String::from_utf8(raw)
        .map_err(|_| ApiError::new("INVALID_ARCHIVE", "tool event content is not UTF-8"))?;
    Ok(json!({ "record": record, "content": content }))
}

#[derive(Deserialize)]
struct CheckpointParams {
    project: String,
    session_id: Option<String>,
    content: String,
}

fn checkpoint(storage: &Storage, params: CheckpointParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let checkpoint_id = storage.archive_checkpoint(
        &project.id,
        params.session_id.as_deref(),
        params.content.as_bytes(),
    )?;
    Ok(json!({ "checkpoint_id": checkpoint_id }))
}

fn parse<T: for<'de> Deserialize<'de>>(value: Value) -> Result<T, ApiError> {
    serde_json::from_value(value)
        .map_err(|error| ApiError::new("INVALID_PARAMS", error.to_string()))
}

fn parse_uuid(value: &str, field: &'static str) -> Result<Uuid, ApiError> {
    Uuid::parse_str(value)
        .map_err(|_| ApiError::new("INVALID_PARAMS", format!("{field} must be a UUID")))
}

struct ApiError {
    code: &'static str,
    message: String,
}

impl ApiError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl From<StorageError> for ApiError {
    fn from(error: StorageError) -> Self {
        Self::new("STORAGE_ERROR", error.to_string())
    }
}

impl From<serde_json::Error> for ApiError {
    fn from(error: serde_json::Error) -> Self {
        Self::new("SERIALIZATION_ERROR", error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use memory_palace_protocol::Request;

    #[test]
    fn protocol_logs_and_searches_a_project_scoped_decision() {
        let storage = Storage::open_in_memory().unwrap();
        let logged = dispatch(
            &storage,
            Request::new(
                "1",
                "memory.log_decision",
                json!({
                    "project": "palace",
                    "decision": "Use a Unix domain socket",
                    "reason": "It avoids a local HTTP hop",
                    "affected_files": ["crates/memory-palace-daemon/src/lib.rs"],
                    "tags": ["transport"]
                }),
            ),
        );
        assert!(logged.ok, "{logged:?}");

        let searched = dispatch(
            &storage,
            Request::new(
                "2",
                "memory.search",
                json!({
                    "project": "palace",
                    "query": "unix socket"
                }),
            ),
        );
        assert!(searched.ok, "{searched:?}");
        assert_eq!(searched.result.unwrap().as_array().unwrap().len(), 1);
    }

    #[test]
    fn unsupported_versions_fail_without_touching_storage() {
        let storage = Storage::open_in_memory().unwrap();
        let mut request = Request::new("1", "health", json!({}));
        request.version = 99;
        let response = dispatch(&storage, request);
        assert!(!response.ok);
        assert_eq!(response.error.unwrap().code, "INVALID_REQUEST");
    }

    #[test]
    fn protocol_edits_removes_and_overrides_conflicts() {
        let storage = Storage::open_in_memory().unwrap();
        let logged = dispatch(
            &storage,
            Request::new(
                "1",
                "memory.log_decision",
                json!({
                    "project": "palace",
                    "decision": "Use the old cache",
                    "reason": "Initial experiment"
                }),
            ),
        );
        let decision_id = logged.result.unwrap()["id"].as_str().unwrap().to_owned();

        let edited = dispatch(
            &storage,
            Request::new(
                "2",
                "memory.edit_decision",
                json!({
                    "project": "palace",
                    "decision_id": decision_id,
                    "decision": "Use the deterministic cache",
                    "reason": "Stable invalidation is required",
                    "tags": ["cache"]
                }),
            ),
        );
        assert!(edited.ok, "{edited:?}");

        let conflict = dispatch(
            &storage,
            Request::new(
                "3",
                "conflict.record",
                json!({
                    "project": "palace",
                    "decision_id": decision_id,
                    "new_intent": "Remove the cache",
                    "explanation": "The request reverses a saved decision"
                }),
            ),
        );
        let conflict_id = conflict.result.unwrap()["id"].as_str().unwrap().to_owned();
        let overridden = dispatch(
            &storage,
            Request::new(
                "4",
                "conflict.override",
                json!({
                    "project": "palace",
                    "conflict_id": conflict_id,
                    "reason": "Requirements changed"
                }),
            ),
        );
        assert_eq!(
            overridden.result.unwrap()["status"].as_str(),
            Some("overridden")
        );

        let removed = dispatch(
            &storage,
            Request::new(
                "5",
                "memory.remove",
                json!({"project": "palace", "decision_id": decision_id}),
            ),
        );
        assert!(removed.ok, "{removed:?}");
        let searched = dispatch(
            &storage,
            Request::new(
                "6",
                "memory.search",
                json!({"project": "palace", "query": "deterministic cache"}),
            ),
        );
        assert!(searched.result.unwrap().as_array().unwrap().is_empty());
    }

    #[test]
    fn protocol_archives_and_recovers_turn_and_tool_evidence() {
        let storage = Storage::open_in_memory().unwrap();
        let archived_turn = dispatch(
            &storage,
            Request::new(
                "1",
                "turn.archive",
                json!({
                    "project": "palace",
                    "session_id": "session-1",
                    "user_text": "Run tests",
                    "assistant_text": "Tests passed",
                    "summary": "Test run",
                    "content": "{\"raw\":\"turn — 測試\"}",
                    "estimated_tokens": 8
                }),
            ),
        );
        assert!(archived_turn.ok, "{archived_turn:?}");
        let turn_id = archived_turn.result.unwrap()["id"]
            .as_str()
            .unwrap()
            .to_owned();
        let recovered_turn = dispatch(
            &storage,
            Request::new(
                "2",
                "turn.get",
                json!({"project": "palace", "turn_id": turn_id}),
            ),
        );
        assert_eq!(
            recovered_turn.result.unwrap()["content"].as_str(),
            Some("{\"raw\":\"turn — 測試\"}")
        );

        let archived_tool = dispatch(
            &storage,
            Request::new(
                "3",
                "tool_event.archive",
                json!({
                    "project": "palace",
                    "turn_id": turn_id,
                    "tool_name": "shell",
                    "invocation_summary": "cargo test",
                    "result_summary": "passed",
                    "content": "full compiler output",
                    "estimated_tokens": 4
                }),
            ),
        );
        assert!(archived_tool.ok, "{archived_tool:?}");
        let event_id = archived_tool.result.unwrap()["id"]
            .as_str()
            .unwrap()
            .to_owned();
        let recovered_tool = dispatch(
            &storage,
            Request::new(
                "4",
                "tool_event.get",
                json!({"project": "palace", "event_id": event_id}),
            ),
        );
        assert_eq!(
            recovered_tool.result.unwrap()["content"].as_str(),
            Some("full compiler output")
        );
    }
}

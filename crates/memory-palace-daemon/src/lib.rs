use memory_palace_core::NewDecision;
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
}

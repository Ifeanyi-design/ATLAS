use memory_palace_core::{
    ConflictId, DecisionId, DecisionPatch, NewDecision, NewToolEvent, NewTurn, ToolEventId, TurnId,
};
use memory_palace_protocol::{MAX_FRAME_BYTES, PROTOCOL_VERSION, Request, Response, encode_frame};
use memory_palace_sqlite::{Storage, StorageError};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
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
        "memory.capsule" => parse::<CapsuleParams>(request.params)
            .and_then(|params| memory_capsule(storage, params)),
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
        "turn.ingest" => parse::<IngestTurnParams>(request.params)
            .and_then(|params| ingest_turn(storage, params)),
        "turn.get" => {
            parse::<GetTurnParams>(request.params).and_then(|params| get_turn(storage, params))
        }
        "tool_event.archive" => parse::<ArchiveToolEventParams>(request.params)
            .and_then(|params| archive_tool_event(storage, params)),
        "tool_event.get" => parse::<GetToolEventParams>(request.params)
            .and_then(|params| get_tool_event(storage, params)),
        "context.prune" => parse::<PruneContextParams>(request.params)
            .and_then(|params| prune_context(storage, params)),
        "context.select" => parse::<SelectContextParams>(request.params)
            .and_then(|params| select_context(storage, params)),
        "checkpoint.archive" => {
            parse::<CheckpointParams>(request.params).and_then(|params| checkpoint(storage, params))
        }
        "checkpoint.get" => parse::<GetCheckpointParams>(request.params)
            .and_then(|params| get_checkpoint(storage, params)),
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
struct CapsuleParams {
    project: String,
    query: String,
    #[serde(default = "default_capsule_chars")]
    max_chars: usize,
}

const fn default_capsule_chars() -> usize {
    8_000
}

fn memory_capsule(storage: &Storage, params: CapsuleParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let content = build_capsule(
        storage,
        &project,
        &params.query,
        params.max_chars.clamp(256, 24_000),
        8_000,
        10_000,
        &[],
    )?;
    Ok(json!({ "content": content }))
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
struct IngestTurnParams {
    project: String,
    session_id: Option<String>,
    user_text: String,
    assistant_text: String,
    #[serde(default)]
    summary: String,
    messages: Vec<Value>,
    #[serde(default)]
    estimated_tokens: i64,
}

fn ingest_turn(storage: &Storage, params: IngestTurnParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let raw = serde_json::to_vec(&params.messages)?;
    let turn = storage.archive_turn(&NewTurn {
        project_id: project.id.clone(),
        session_id: params.session_id,
        user_text: params.user_text,
        assistant_text: params.assistant_text,
        summary: params.summary,
        raw,
        estimated_tokens: params.estimated_tokens,
    })?;
    let calls = tool_calls(&params.messages);
    let mut events = Vec::new();
    for message in &params.messages {
        if message_role(message) != Some("tool") {
            continue;
        }
        events.push(archive_message_tool_event(
            storage,
            &project.id,
            Some(&turn.id),
            message,
            &calls,
        )?);
    }
    Ok(json!({ "turn": turn, "tool_events": events }))
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

#[derive(Deserialize)]
struct GetCheckpointParams {
    project: String,
    checkpoint_id: String,
}

fn get_checkpoint(storage: &Storage, params: GetCheckpointParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let raw = storage
        .recover_checkpoint(&project.id, &params.checkpoint_id)?
        .ok_or_else(|| ApiError::new("NOT_FOUND", "checkpoint was not found"))?;
    let content = String::from_utf8(raw)
        .map_err(|_| ApiError::new("INVALID_ARCHIVE", "checkpoint content is not UTF-8"))?;
    Ok(json!({ "checkpoint_id": params.checkpoint_id, "content": content }))
}

#[derive(Deserialize)]
struct PruneContextParams {
    project: String,
    messages: Vec<Value>,
    #[serde(default = "default_min_result_chars")]
    min_result_chars: usize,
}

const fn default_min_result_chars() -> usize {
    4_096
}

fn prune_context(storage: &Storage, params: PruneContextParams) -> Result<Value, ApiError> {
    let project = storage.resolve_project(&params.project)?;
    let mut messages = params.messages;
    let active_start = active_turn_start(&messages);
    let calls = tool_calls(&messages);
    let mut pruned = 0usize;
    for message in messages.iter_mut().take(active_start) {
        if message_role(message) != Some("tool") {
            continue;
        }
        let content = message_content(message);
        if content.chars().count() < params.min_result_chars.max(256) {
            continue;
        }
        let event = ensure_message_tool_event(storage, &project.id, message, &calls)?;
        if let Some(object) = message.as_object_mut() {
            object.insert(
                "content".to_owned(),
                Value::String(tool_reference(&event.id.to_string(), &event.result_summary)),
            );
            pruned += 1;
        }
    }
    Ok(json!({ "messages": messages, "pruned": pruned }))
}

#[derive(Deserialize)]
struct SelectContextParams {
    project: String,
    messages: Vec<Value>,
    #[serde(default)]
    query: String,
    #[serde(default = "default_trigger_tokens")]
    trigger_tokens: usize,
    #[serde(default = "default_target_dynamic_tokens")]
    target_dynamic_tokens: usize,
    #[serde(default = "default_decision_tokens")]
    max_decision_tokens: usize,
    #[serde(default = "default_turn_tokens")]
    max_retrieved_turn_tokens: usize,
}

const fn default_trigger_tokens() -> usize {
    24_000
}
const fn default_target_dynamic_tokens() -> usize {
    8_000
}
const fn default_decision_tokens() -> usize {
    2_000
}
const fn default_turn_tokens() -> usize {
    2_500
}

fn select_context(storage: &Storage, params: SelectContextParams) -> Result<Value, ApiError> {
    let original_tokens = estimate_messages_tokens(&params.messages);
    if original_tokens < params.trigger_tokens.max(1) {
        return Ok(json!({
            "messages": params.messages,
            "selected": false,
            "original_tokens": original_tokens,
            "selected_tokens": original_tokens,
            "archived_tool_events": 0
        }));
    }

    let project = storage.resolve_project(&params.project)?;
    let active_start = active_turn_start(&params.messages);
    let prefix_end = leading_system_end(&params.messages);
    let calls = tool_calls(&params.messages);
    let mut archived = Vec::new();
    for message in params.messages.iter().take(active_start) {
        if message_role(message) == Some("tool") {
            archived.push(ensure_message_tool_event(
                storage,
                &project.id,
                message,
                &calls,
            )?);
        }
    }

    let query = if params.query.trim().is_empty() {
        params
            .messages
            .get(active_start)
            .map(message_content)
            .unwrap_or_default()
    } else {
        params.query
    };
    let active = &params.messages[active_start..];
    let active_tokens = estimate_messages_tokens(active);
    let target = params.target_dynamic_tokens.max(512);
    let capsule_tokens = target.saturating_sub(active_tokens).max(256);
    let refs = archived
        .iter()
        .rev()
        .take(12)
        .map(|event| (event.id.to_string(), event.result_summary.clone()))
        .collect::<Vec<_>>();
    let capsule = build_capsule(
        storage,
        &project,
        &query,
        capsule_tokens.saturating_mul(4),
        params.max_decision_tokens.saturating_mul(4),
        params.max_retrieved_turn_tokens.saturating_mul(4),
        &refs,
    )?;

    let mut selected = Vec::new();
    selected.extend(params.messages.iter().take(prefix_end).cloned());
    if !capsule.is_empty() {
        selected.push(json!({
            "role": "system",
            "content": format!("MEMORY PALACE CONTEXT (selected, recoverable)\n{capsule}")
        }));
    }
    selected.extend(active.iter().cloned());
    let selected_tokens = estimate_messages_tokens(&selected);
    Ok(json!({
        "messages": selected,
        "selected": true,
        "original_tokens": original_tokens,
        "selected_tokens": selected_tokens,
        "archived_tool_events": archived.len()
    }))
}

#[derive(Debug, Clone)]
struct ToolCallInfo {
    name: String,
    arguments: String,
}

fn tool_calls(messages: &[Value]) -> BTreeMap<String, ToolCallInfo> {
    let mut calls = BTreeMap::new();
    for message in messages {
        let Some(items) = message.get("tool_calls").and_then(Value::as_array) else {
            continue;
        };
        for call in items {
            let Some(id) = call.get("id").and_then(Value::as_str) else {
                continue;
            };
            let function = call.get("function").unwrap_or(&Value::Null);
            calls.insert(
                id.to_owned(),
                ToolCallInfo {
                    name: function
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("tool")
                        .to_owned(),
                    arguments: function
                        .get("arguments")
                        .map(value_text)
                        .unwrap_or_default(),
                },
            );
        }
    }
    calls
}

fn archive_message_tool_event(
    storage: &Storage,
    project_id: &memory_palace_core::ProjectId,
    turn_id: Option<&TurnId>,
    message: &Value,
    calls: &BTreeMap<String, ToolCallInfo>,
) -> Result<memory_palace_core::ArchivedToolEvent, ApiError> {
    let call = message
        .get("tool_call_id")
        .and_then(Value::as_str)
        .and_then(|id| calls.get(id));
    let content = message_content(message);
    Ok(storage.archive_tool_event(&NewToolEvent {
        project_id: project_id.clone(),
        turn_id: turn_id.cloned(),
        tool_name: message
            .get("name")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or_else(|| call.map(|item| item.name.clone()))
            .unwrap_or_else(|| "tool".to_owned()),
        invocation_summary: compact_text(
            call.map(|item| item.arguments.as_str())
                .unwrap_or("tool invocation"),
            320,
        ),
        result_summary: compact_tool_result(&content),
        raw: content.into_bytes(),
        estimated_tokens: 0,
    })?)
}

fn ensure_message_tool_event(
    storage: &Storage,
    project_id: &memory_palace_core::ProjectId,
    message: &Value,
    calls: &BTreeMap<String, ToolCallInfo>,
) -> Result<memory_palace_core::ArchivedToolEvent, ApiError> {
    let content = message_content(message);
    if let Some(event) = storage.find_tool_event_by_content(project_id, content.as_bytes())? {
        return Ok(event);
    }
    archive_message_tool_event(storage, project_id, None, message, calls)
}

fn build_capsule(
    storage: &Storage,
    project: &memory_palace_core::Project,
    query: &str,
    max_chars: usize,
    max_decision_chars: usize,
    max_evidence_chars: usize,
    archived_refs: &[(String, String)],
) -> Result<String, ApiError> {
    let mut sections = vec![format!("Project: {}", project.name)];
    if !project.summary.trim().is_empty() {
        sections.push(format!("Project state:\n{}", project.summary.trim()));
    }

    let decisions = storage.search_decisions(&project.id, query, 12)?;
    let mut decision_lines = Vec::new();
    let mut decision_chars = 0usize;
    for hit in decisions {
        let line = format!(
            "- {}: {}\n  Reason: {}",
            hit.decision.id, hit.decision.decision, hit.decision.reason
        );
        if decision_chars + line.chars().count() > max_decision_chars {
            break;
        }
        decision_chars += line.chars().count();
        decision_lines.push(line);
    }
    if !decision_lines.is_empty() {
        sections.push(format!(
            "Relevant decisions:\n{}",
            decision_lines.join("\n")
        ));
    }

    let evidence = storage.search_evidence(&project.id, query, 10)?;
    let mut evidence_lines = Vec::new();
    let mut evidence_chars = 0usize;
    for hit in evidence {
        let scheme = if hit.kind == "tool_event" {
            "tool"
        } else {
            "turn"
        };
        let line = format!("- {}\n  Evidence: mp://{}/{}", hit.summary, scheme, hit.id);
        if evidence_chars + line.chars().count() > max_evidence_chars {
            break;
        }
        evidence_chars += line.chars().count();
        evidence_lines.push(line);
    }
    if !evidence_lines.is_empty() {
        sections.push(format!(
            "Relevant prior work:\n{}",
            evidence_lines.join("\n")
        ));
    }

    let conflicts = storage.open_conflicts(&project.id, 6)?;
    if !conflicts.is_empty() {
        sections.push(format!(
            "Open conflict warnings:\n{}",
            conflicts
                .iter()
                .map(|item| format!("- {}: {} ({})", item.id, item.new_intent, item.explanation))
                .collect::<Vec<_>>()
                .join("\n")
        ));
    }
    if !archived_refs.is_empty() {
        sections.push(format!(
            "Recently archived tool evidence:\n{}",
            archived_refs
                .iter()
                .map(|(id, summary)| format!("- {} — mp://tool/{}", compact_text(summary, 180), id))
                .collect::<Vec<_>>()
                .join("\n")
        ));
    }
    Ok(compact_text(&sections.join("\n\n"), max_chars.max(256)))
}

fn message_role(message: &Value) -> Option<&str> {
    message.get("role").and_then(Value::as_str)
}

fn message_content(message: &Value) -> String {
    message.get("content").map(value_text).unwrap_or_default()
}

fn value_text(value: &Value) -> String {
    value
        .as_str()
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| serde_json::to_string(value).unwrap_or_default())
}

fn active_turn_start(messages: &[Value]) -> usize {
    messages
        .iter()
        .rposition(|message| message_role(message) == Some("user"))
        .unwrap_or_else(|| leading_system_end(messages))
}

fn leading_system_end(messages: &[Value]) -> usize {
    messages
        .iter()
        .take_while(|message| matches!(message_role(message), Some("system" | "developer")))
        .count()
}

fn estimate_messages_tokens(messages: &[Value]) -> usize {
    serde_json::to_vec(messages)
        .map(|bytes| bytes.len().div_ceil(4))
        .unwrap_or(0)
}

fn compact_tool_result(content: &str) -> String {
    let compact = content.split_whitespace().collect::<Vec<_>>().join(" ");
    compact_text(&compact, 360)
}

fn compact_text(content: &str, max_chars: usize) -> String {
    let length = content.chars().count();
    if length <= max_chars {
        return content.to_owned();
    }
    if max_chars < 32 {
        return content.chars().take(max_chars).collect();
    }
    let head = max_chars.saturating_sub(18);
    format!(
        "{} …[truncated]",
        content.chars().take(head).collect::<String>()
    )
}

fn tool_reference(id: &str, summary: &str) -> String {
    format!(
        "[Archived tool result {id}]\n{}\nFull evidence: mp://tool/{id}",
        compact_text(summary, 360)
    )
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

    #[test]
    fn ingest_turn_archives_each_tool_result_in_rust() {
        let storage = Storage::open_in_memory().unwrap();
        let response = dispatch(
            &storage,
            Request::new(
                "1",
                "turn.ingest",
                json!({
                    "project": "palace",
                    "session_id": "session-1",
                    "user_text": "Run tests",
                    "assistant_text": "One test failed",
                    "messages": [
                        {"role": "user", "content": "Run tests"},
                        {"role": "assistant", "tool_calls": [{
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "terminal", "arguments": "{\"cmd\":\"cargo test\"}"}
                        }]},
                        {"role": "tool", "tool_call_id": "call-1", "content": "retry_test failed — 測試"},
                        {"role": "assistant", "content": "One test failed"}
                    ]
                }),
            ),
        );
        assert!(response.ok, "{response:?}");
        let result = response.result.unwrap();
        assert_eq!(result["tool_events"].as_array().unwrap().len(), 1);
        assert_eq!(result["tool_events"][0]["tool_name"], "terminal");
        let event_id = result["tool_events"][0]["id"].as_str().unwrap();
        let recovered = dispatch(
            &storage,
            Request::new(
                "2",
                "tool_event.get",
                json!({"project": "palace", "event_id": event_id}),
            ),
        );
        assert_eq!(
            recovered.result.unwrap()["content"],
            "retry_test failed — 測試"
        );
    }

    #[test]
    fn long_context_selection_is_stable_safe_and_recoverable() {
        let storage = Storage::open_in_memory().unwrap();
        let logged = dispatch(
            &storage,
            Request::new(
                "decision",
                "memory.log_decision",
                json!({
                    "project": "palace",
                    "decision": "Retry counters must be persisted before reset",
                    "reason": "A failed webhook must retain its backoff state",
                    "tags": ["webhook", "retry"],
                    "importance": 5
                }),
            ),
        );
        assert!(logged.ok);
        let other_project = dispatch(
            &storage,
            Request::new(
                "other-decision",
                "memory.log_decision",
                json!({
                    "project": "other-project",
                    "decision": "Webhook retry secrets belong to another project",
                    "reason": "This must never cross the project boundary"
                }),
            ),
        );
        assert!(other_project.ok);

        let system = json!({"role": "system", "content": "immutable hermes harness"});
        let mut messages = vec![system.clone()];
        let large_output = format!("compiler output retry_count=0 {}", "x".repeat(16_000));
        for index in 0..25 {
            messages.push(json!({"role": "user", "content": format!("old task {index}")}));
            messages.push(json!({"role": "assistant", "tool_calls": [{
                "id": format!("call-{index}"),
                "type": "function",
                "function": {"name": "terminal", "arguments": format!("test suite {index}")}
            }]}));
            messages.push(json!({
                "role": "tool",
                "tool_call_id": format!("call-{index}"),
                "content": format!("{large_output}-{index}")
            }));
            messages.push(json!({"role": "assistant", "content": "Recorded test result"}));
        }
        let active = vec![
            json!({"role": "user", "content": "Fix the webhook retry counter"}),
            json!({"role": "assistant", "tool_calls": [{
                "id": "active-call",
                "type": "function",
                "function": {"name": "terminal", "arguments": "inspect retry code"}
            }]}),
            json!({"role": "tool", "tool_call_id": "active-call", "content": "active result"}),
        ];
        messages.extend(active.clone());
        let request = || {
            Request::new(
                "select",
                "context.select",
                json!({
                    "project": "palace",
                    "messages": messages,
                    "query": "webhook retry counter",
                    "trigger_tokens": 1000,
                    "target_dynamic_tokens": 2000
                }),
            )
        };
        let first = dispatch(&storage, request());
        assert!(first.ok, "{first:?}");
        let first = first.result.unwrap();
        let selected = first["messages"].as_array().unwrap();
        assert_eq!(selected.first(), Some(&system));
        assert_eq!(
            &selected[selected.len() - active.len()..],
            active.as_slice()
        );
        assert!(first["selected"].as_bool().unwrap());
        let original_tokens = first["original_tokens"].as_u64().unwrap();
        let selected_tokens = first["selected_tokens"].as_u64().unwrap();
        assert!(
            selected_tokens * 5 < original_tokens,
            "{selected_tokens}/{original_tokens}"
        );
        assert!(
            selected[1]["content"]
                .as_str()
                .unwrap()
                .contains("Retry counters must be persisted")
        );
        assert!(
            !selected[1]["content"]
                .as_str()
                .unwrap()
                .contains("another project")
        );
        assert_eq!(first["archived_tool_events"], 25);

        let evidence = storage
            .search_evidence(
                &storage.resolve_project("palace").unwrap().id,
                "retry count",
                1,
            )
            .unwrap();
        assert!(!evidence.is_empty());
        let event_id = ToolEventId(Uuid::parse_str(&evidence[0].id).unwrap());
        let raw = storage
            .recover_tool_event(&storage.resolve_project("palace").unwrap().id, &event_id)
            .unwrap()
            .unwrap();
        assert!(String::from_utf8(raw).unwrap().contains("retry_count=0"));

        let second = dispatch(&storage, request()).result.unwrap();
        assert_eq!(first["messages"], second["messages"]);
        assert_eq!(storage.status().unwrap().tool_events, 25);
    }

    #[test]
    fn prune_archives_old_large_tools_but_preserves_active_tool_pair() {
        let storage = Storage::open_in_memory().unwrap();
        let old = "z".repeat(8_000);
        let messages = vec![
            json!({"role": "system", "content": "harness"}),
            json!({"role": "user", "content": "old"}),
            json!({"role": "assistant", "tool_calls": [{"id": "old-call", "function": {"name": "shell", "arguments": "build"}}]}),
            json!({"role": "tool", "tool_call_id": "old-call", "content": old}),
            json!({"role": "assistant", "content": "old done"}),
            json!({"role": "user", "content": "current"}),
            json!({"role": "assistant", "tool_calls": [{"id": "live-call", "function": {"name": "shell", "arguments": "test"}}]}),
            json!({"role": "tool", "tool_call_id": "live-call", "content": "live result"}),
        ];
        let response = dispatch(
            &storage,
            Request::new(
                "1",
                "context.prune",
                json!({"project": "palace", "messages": messages, "min_result_chars": 1000}),
            ),
        );
        assert!(response.ok, "{response:?}");
        let result = response.result.unwrap();
        assert_eq!(result["pruned"], 1);
        assert!(
            result["messages"][3]["content"]
                .as_str()
                .unwrap()
                .contains("mp://tool/")
        );
        assert_eq!(result["messages"][7]["content"], "live result");
    }

    #[test]
    fn checkpoint_protocol_is_idempotent_and_recoverable() {
        let storage = Storage::open_in_memory().unwrap();
        let archive = || {
            dispatch(
                &storage,
                Request::new(
                    "archive",
                    "checkpoint.archive",
                    json!({
                        "project": "palace",
                        "session_id": "session-1",
                        "content": "durable transcript — 記憶"
                    }),
                ),
            )
        };
        let first = archive().result.unwrap()["checkpoint_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let second = archive().result.unwrap()["checkpoint_id"]
            .as_str()
            .unwrap()
            .to_owned();
        assert_eq!(first, second);
        assert!(first.starts_with("memory-palace:checkpoint:sha256:"));
        assert_eq!(storage.status().unwrap().checkpoints, 1);

        let recovered = dispatch(
            &storage,
            Request::new(
                "get",
                "checkpoint.get",
                json!({"project": "palace", "checkpoint_id": first}),
            ),
        );
        assert_eq!(
            recovered.result.unwrap()["content"],
            "durable transcript — 記憶"
        );
    }
}

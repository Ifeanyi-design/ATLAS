use serde::{Deserialize, Serialize};
use std::fmt;
use uuid::Uuid;

pub const DELETE_ALL_CONFIRMATION: &str = "DELETE ALL PROJECT MEMORY";

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ProjectId(pub Uuid);

impl ProjectId {
    pub fn new() -> Self {
        Self(Uuid::now_v7())
    }
}

impl Default for ProjectId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for ProjectId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct DecisionId(pub Uuid);

impl DecisionId {
    pub fn new() -> Self {
        Self(Uuid::now_v7())
    }
}

impl Default for DecisionId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for DecisionId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

macro_rules! uuid_id {
    ($name:ident) => {
        #[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(pub Uuid);

        impl $name {
            pub fn new() -> Self {
                Self(Uuid::now_v7())
            }
        }

        impl Default for $name {
            fn default() -> Self {
                Self::new()
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(f)
            }
        }
    };
}

uuid_id!(TurnId);
uuid_id!(ToolEventId);
uuid_id!(ConflictId);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionStatus {
    Active,
    Superseded,
    Retracted,
}

impl DecisionStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Superseded => "superseded",
            Self::Retracted => "retracted",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Project {
    pub id: ProjectId,
    pub name: String,
    pub summary: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NewDecision {
    pub project_id: ProjectId,
    pub session_id: Option<String>,
    pub decision: String,
    pub reason: String,
    #[serde(default)]
    pub affected_files: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default = "default_importance")]
    pub importance: i64,
    pub source_turn_id: Option<String>,
}

const fn default_importance() -> i64 {
    3
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Decision {
    pub id: DecisionId,
    pub project_id: ProjectId,
    pub session_id: Option<String>,
    pub decision: String,
    pub reason: String,
    pub status: DecisionStatus,
    pub importance: i64,
    pub affected_files: Vec<String>,
    pub tags: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    pub superseded_by: Option<DecisionId>,
    pub source_turn_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchHit {
    #[serde(flatten)]
    pub decision: Decision,
    pub score: f64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionPatch {
    pub decision: Option<String>,
    pub reason: Option<String>,
    pub affected_files: Option<Vec<String>>,
    pub tags: Option<Vec<String>>,
    pub importance: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NewTurn {
    pub project_id: ProjectId,
    pub session_id: Option<String>,
    pub user_text: String,
    pub assistant_text: String,
    pub summary: String,
    pub raw: Vec<u8>,
    pub estimated_tokens: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArchivedTurn {
    pub id: TurnId,
    pub project_id: ProjectId,
    pub session_id: Option<String>,
    pub user_text: String,
    pub assistant_text: String,
    pub summary: String,
    pub raw_sha256: String,
    pub estimated_tokens: i64,
    pub created_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NewToolEvent {
    pub project_id: ProjectId,
    pub turn_id: Option<TurnId>,
    pub tool_name: String,
    pub invocation_summary: String,
    pub result_summary: String,
    pub raw: Vec<u8>,
    pub estimated_tokens: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArchivedToolEvent {
    pub id: ToolEventId,
    pub project_id: ProjectId,
    pub turn_id: Option<TurnId>,
    pub tool_name: String,
    pub invocation_summary: String,
    pub result_summary: String,
    pub raw_sha256: String,
    pub estimated_tokens: i64,
    pub created_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Conflict {
    pub id: ConflictId,
    pub project_id: ProjectId,
    pub decision_id: Option<DecisionId>,
    pub new_intent: String,
    pub explanation: String,
    pub status: String,
    pub override_reason: Option<String>,
    pub created_at: String,
    pub overridden_at: Option<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum DomainError {
    #[error("{field} must not be empty")]
    EmptyField { field: &'static str },
    #[error("importance must be between 1 and 5")]
    InvalidImportance,
    #[error("estimated tokens must not be negative")]
    InvalidEstimatedTokens,
}

impl NewDecision {
    pub fn validate(&self) -> Result<(), DomainError> {
        if self.decision.trim().is_empty() {
            return Err(DomainError::EmptyField { field: "decision" });
        }
        if self.reason.trim().is_empty() {
            return Err(DomainError::EmptyField { field: "reason" });
        }
        if !(1..=5).contains(&self.importance) {
            return Err(DomainError::InvalidImportance);
        }
        Ok(())
    }
}

impl DecisionPatch {
    pub fn validate(&self) -> Result<(), DomainError> {
        if self
            .decision
            .as_ref()
            .is_some_and(|value| value.trim().is_empty())
        {
            return Err(DomainError::EmptyField { field: "decision" });
        }
        if self
            .reason
            .as_ref()
            .is_some_and(|value| value.trim().is_empty())
        {
            return Err(DomainError::EmptyField { field: "reason" });
        }
        if self
            .importance
            .is_some_and(|value| !(1..=5).contains(&value))
        {
            return Err(DomainError::InvalidImportance);
        }
        Ok(())
    }
}

impl NewTurn {
    pub fn validate(&self) -> Result<(), DomainError> {
        if self.user_text.trim().is_empty() && self.assistant_text.trim().is_empty() {
            return Err(DomainError::EmptyField {
                field: "turn content",
            });
        }
        if self.estimated_tokens < 0 {
            return Err(DomainError::InvalidEstimatedTokens);
        }
        Ok(())
    }
}

impl NewToolEvent {
    pub fn validate(&self) -> Result<(), DomainError> {
        if self.tool_name.trim().is_empty() {
            return Err(DomainError::EmptyField { field: "tool name" });
        }
        if self.estimated_tokens < 0 {
            return Err(DomainError::InvalidEstimatedTokens);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_decision_requires_reason_and_bounded_importance() {
        let mut value = NewDecision {
            project_id: ProjectId::new(),
            session_id: None,
            decision: "Use SQLite".into(),
            reason: "Local-first".into(),
            affected_files: vec![],
            tags: vec![],
            importance: 3,
            source_turn_id: None,
        };
        assert!(value.validate().is_ok());
        value.reason.clear();
        assert!(matches!(
            value.validate(),
            Err(DomainError::EmptyField { field: "reason" })
        ));
    }
}

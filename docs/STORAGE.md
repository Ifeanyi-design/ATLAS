# Storage

SQLite is authoritative for local version 1. The native binary uses a bundled
SQLite build and enables foreign keys, a five-second busy timeout, WAL for file
databases, and `synchronous=NORMAL`.

The initial migration creates normalized projects, sessions, decisions, affected
files, tags, conflicts, turns, tool events, and checkpoints. FTS5 indexes decision
text, rationale, paths, and tags. Every query includes an exact project filter.

Checkpoint evidence is SHA-256 addressed and zstd compressed before insertion.
Checkpoint rows carry project and session scope even when two projects archive
identical bytes.

Completed turns and tool events use the same zstd archival path. Recovery always
requires the owning project ID and verifies the decompressed bytes against the
stored SHA-256 digest before returning evidence. Decision edits replace their FTS
document in the same transaction, while decision deletion removes its FTS row so
deleted or stale text cannot be retrieved.

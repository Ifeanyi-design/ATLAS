# Architecture

Memory Palace is a Linux-only, local-first memory service for Hermes Agent.

```text
Hermes MemoryProvider adapter
        |
        | newline-delimited JSON protocol v1
        v
Unix domain socket (mode 0600)
        |
        v
memory-palace Rust daemon
        |
        +-- core domain types and validation
        +-- deterministic SQLite FTS5 retrieval
        `-- SQLite WAL store with zstd evidence blobs
```

The Cargo workspace isolates portable domain and protocol types from native Linux
transport and SQLite code. This leaves room for a later D1/WASM storage adapter
without introducing cloud dependencies into the local binary.

## Protocol framing

Protocol v1 uses one UTF-8 JSON object per line. Requests and responses carry a
version and correlation ID. Both peers enforce a 64 MiB frame limit. The contract
contains JSON values only and does not expose Rust types.

## Failure boundaries

Ordinary retrieval is intended to fail open once context selection is added.
Pre-compression checkpoint writes are content-addressed, zstd-compressed,
idempotent within a project/session, and acknowledged only after the SQLite
transaction commits.

## Hermes loaders

As of the Phase 0 audit, current Hermes uses separate single-select discovery for
memory providers and context engines. Memory Palace therefore ships separate
Hermes-facing directories sharing one socket protocol. It does not modify Hermes
core.

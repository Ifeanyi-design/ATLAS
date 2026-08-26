# Architecture

Memory Palace is a Unix-native, distro-agnostic local memory service for Hermes
Agent. It depends on Unix domain sockets, not a particular package manager,
service manager, or filesystem layout.

```text
Hermes MemoryProvider + ContextEngine adapters
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

Decision logging performs deterministic conflict screening in Rust. Change or
opposition language is matched against project-scoped active decisions using
FTS candidates, lexical overlap, affected files, and tags. Matches are saved as
open warnings alongside the new decision; they never block the write, and an
explicit override remains auditable.

## Protocol framing

Protocol v1 uses one UTF-8 JSON object per line. Requests and responses carry a
version and correlation ID. Both peers enforce a 64 MiB frame limit. The contract
contains JSON values only and does not expose Rust types.

## Failure boundaries

Ordinary prefetch, tool pruning, and request-time context selection fail open.
Persistent compression fails closed: the context engine returns the original
transcript unless a content-addressed, zstd-compressed checkpoint commits with
SQLite `synchronous=FULL`. Ordinary writes retain WAL + `synchronous=NORMAL`.

## Hermes loaders

Hermes v0.20.3 classifies provider directories as exclusive plugins, while
context engines are loaded through the general plugin manager. Memory Palace
therefore ships `memory-palace` and `memory-palace-context` directories. They
share one socket protocol and do not modify Hermes core.

Tagged releases package a static x86-64 Linux musl binary with both adapters and
a SHA-256 sidecar. The bootstrap verifies the archive before extraction and
falls back to a locked local Cargo build when no matching verified artifact is
available.

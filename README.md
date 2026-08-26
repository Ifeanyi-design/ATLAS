# Hermes Memory Palace

Rust-native persistent engineering memory for
[Hermes Agent](https://github.com/NousResearch/hermes-agent).

Memory Palace stores project decisions and their rationale locally, retrieves
them through deterministic SQLite FTS5 search, and durably checkpoints evidence
before Hermes performs lossy context compression. It is a staged rewrite derived
from ATLAS's engineering-decision memory concept.

The current implementation is local-first and works without Docker, PostgreSQL,
an OpenAI key, remote embeddings, or a Python application server.

## Install with Hermes

Hermes can run the bootstrap directly:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/drbree82/hermes-memory-palace/main/scripts/install.sh | sh
```

The installer:

1. downloads and SHA-256 verifies the latest static Linux release when one is
   available for the host;
2. otherwise downloads the selected source revision and builds the locked
   Cargo workspace in release mode;
3. installs the profile-owned binary under
   `$HERMES_HOME/memory-palace/bin/`;
4. installs a CLI copy under `${MEMORY_PALACE_BIN_DIR:-$HOME/.local/bin}`;
5. installs the thin provider and context-engine adapters under
   `$HERMES_HOME/plugins/`;
6. enables both adapters and selects them in Hermes when `hermes` is available;
7. runs `memory-palace doctor` against the profile database.

It does not use `sudo`, modify system directories, install Docker, or ask for
credentials. Release installs on x86-64 Linux do not require Rust or a C
compiler. Other architectures, development refs, unavailable assets, or
`MEMORY_PALACE_PREFER_SOURCE=1` use the transparent locked source-build fallback.

To install a specific revision:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/drbree82/hermes-memory-palace/main/scripts/install.sh |
  MEMORY_PALACE_REF=v0.1.0 sh
```

For inspection-first installation, download `scripts/install.sh`, review it, and
run it with `sh`.

## Hermes configuration

The installer selects both adapters in the active Hermes profile:

```yaml
memory:
  provider: memory-palace

context:
  engine: memory-palace
```

Hermes v0.20.3 treats memory-provider pre-compression hooks as advisory. The
Memory Palace context engine therefore enforces the destructive boundary
itself: it synchronously creates a FULL-durable, content-addressed checkpoint
and returns the original transcript unchanged if archival fails.

The provider uses the `hermes_home` value supplied by Hermes. It connects to:

```text
$HERMES_HOME/memory-palace/run/memory-palace.sock
```

If the daemon is not already available, the adapter starts the profile-owned
binary in its own process session and writes output to:

```text
$HERMES_HOME/memory-palace/log/daemon.log
```

## Current capabilities

- project-scoped engineering decisions;
- automatically maintained, bounded project-state summaries;
- rationale, affected-file, tag, importance, and session metadata;
- project-scoped decision reads, edits, selected deletion, and confirmed
  whole-project deletion;
- deterministic lexical/metadata conflict warnings, auditable records, and
  explicit overrides that never block a deliberate change;
- deterministic SQLite FTS5 retrieval;
- bundled SQLite with WAL, foreign keys, busy timeout, and capability checks;
- UUIDv7 identifiers;
- versioned JSON requests over a permission-restricted Unix domain socket;
- SHA-256-addressed, zstd-compressed, idempotent checkpoints;
- recoverable zstd archives for completed turns and large tool results;
- non-blocking completed-turn ingestion and per-tool evidence extraction in Rust;
- bounded automatic prefetch capsules from project decisions and prior evidence;
- deterministic request-time context selection with explicit token budgets;
- archival and compact replacement of stale large tool results;
- fail-open request selection and fail-closed persistent compression;
- Hermes tools for decision logging, search, editing, deletion, conflict
  overrides, and archived evidence recovery;
- Hermes pre-compression checkpoint API v2;
- no mandatory network or model call during normal operation.

## CLI

```sh
memory-palace init
memory-palace serve
memory-palace doctor
memory-palace status
memory-palace search "sqlite" --project my-project
```

`memory-palace` uses `$HERMES_HOME/memory-palace` when `HERMES_HOME` is set.
`--home` or `MEMORY_PALACE_HOME` may be used for isolated development and tests.

## Architecture

```text
Hermes MemoryProvider + ContextEngine
        |
        | standard-library Python client
        v
versioned JSON over Unix socket
        |
        v
memory-palace Rust daemon
        |
        +-- domain and protocol crates
        +-- deterministic retrieval
        `-- bundled SQLite + FTS5 + zstd
```

The Rust workspace separates portable domain/protocol logic from Unix transport
and SQLite storage. Current distribution is Unix-native and package-manager
agnostic: it does not assume a particular Linux distribution, systemd, Homebrew,
or another OS package manager.

Hermes discovers memory providers and context engines independently. The
installer therefore deploys two Hermes-facing plugin directories sharing the
same daemon protocol; all storage, retrieval, archival, and selection logic
remains in Rust.

See:

- [Architecture](docs/ARCHITECTURE.md)
- [Storage](docs/STORAGE.md)
- [Hermes adapter notes](adapters/hermes/README.md)

## Development

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
python3 -m unittest discover -s tests -p 'test_hermes*.py' -v
cargo build --release
./target/release/memory-palace --home /tmp/memory-palace-dev doctor
```

The old ATLAS Python service remains temporarily in the repository as a behavior
and migration reference. It is not part of the Memory Palace install path. Once
the corresponding Rust behavior and migration fixtures are complete, the legacy
runtime can be removed using Git history for preservation.

## Attribution

Hermes Memory Palace is derived from the ATLAS project by Ifeanyi-design. The
original MIT license and attribution are retained in [LICENSE](LICENSE).

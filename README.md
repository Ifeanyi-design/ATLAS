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

1. downloads the selected source revision from GitHub;
2. builds the locked Cargo workspace in release mode;
3. installs the profile-owned binary under
   `$HERMES_HOME/memory-palace/bin/`;
4. installs a CLI copy under `${MEMORY_PALACE_BIN_DIR:-$HOME/.local/bin}`;
5. installs the thin provider under `$HERMES_HOME/plugins/memory-palace/`;
6. runs `memory-palace doctor` against the profile database.

It does not use `sudo`, modify system directories, install Docker, or ask for
credentials. A Rust toolchain and native C compiler are currently required while
the bootstrap builds from source. Prebuilt, checksummed release archives can
replace that build step later without changing the Hermes integration.

To install a specific revision:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/drbree82/hermes-memory-palace/main/scripts/install.sh |
  MEMORY_PALACE_REF=v0.1.0 sh
```

For inspection-first installation, download `scripts/install.sh`, review it, and
run it with `sh`.

## Hermes configuration

Select the provider in the active Hermes profile:

```yaml
memory:
  provider: memory-palace

compression:
  checkpoint_required: true
```

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
- rationale, affected-file, tag, importance, and session metadata;
- project-scoped decision reads, edits, selected deletion, and confirmed
  whole-project deletion;
- auditable conflict records and explicit overrides;
- deterministic SQLite FTS5 retrieval;
- bundled SQLite with WAL, foreign keys, busy timeout, and capability checks;
- UUIDv7 identifiers;
- versioned JSON requests over a permission-restricted Unix domain socket;
- SHA-256-addressed, zstd-compressed, idempotent checkpoints;
- recoverable zstd archives for completed turns and large tool results;
- non-blocking completed-turn ingestion from Hermes;
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
Hermes MemoryProvider
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

Hermes currently discovers memory providers and context engines independently.
The initial adapter implements the memory-provider side. Context selection will
ship as a separate Hermes-facing plugin sharing the same daemon and protocol.

See:

- [Architecture](docs/ARCHITECTURE.md)
- [Storage](docs/STORAGE.md)
- [Hermes adapter notes](adapters/hermes/README.md)

## Development

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
python3 -m unittest discover -s tests -p 'test_hermes_client.py' -v
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

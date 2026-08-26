# Hermes adapters

Hermes v0.20.3 discovers memory providers and context engines through separate
activation paths. It also classifies a directory containing a memory provider as
an exclusive plugin, so one combined directory cannot reliably expose both
interfaces. Memory Palace therefore ships:

- `memory_palace/` for the selected `MemoryProvider`;
- `memory_palace_context/` for the selected `ContextEngine`.

Both are standard-library Python lifecycle adapters over the same versioned Unix
socket. Storage, extraction, search, budgeting, archival, and context selection
remain in Rust.

For development, install both directories as `memory-palace` and
`memory-palace-context` under the active profile's plugin directory, enable both,
then select `memory-palace` as `memory.provider` and `context.engine`. The
adapters expect the daemon at
`$HERMES_HOME/memory-palace/run/memory-palace.sock`.

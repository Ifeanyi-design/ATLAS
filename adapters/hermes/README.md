# Hermes integration spike

The current Hermes runtime discovers memory providers and context engines through
separate single-select plugin loaders. The first integration checkpoint therefore
implements only the memory provider in `memory_palace/`. A future context-engine
plugin will be installed separately and reuse the same versioned Unix-socket
protocol rather than patching Hermes core.

For development, copy or symlink `memory_palace/` to the active profile's plugin
directory and select `memory-palace` as `memory.provider`. The adapter expects the
daemon at `$HERMES_HOME/memory-palace/run/memory-palace.sock` and contains no
storage, ranking, or conflict business logic.

#!/bin/sh
set -eu
umask 077

repository=${MEMORY_PALACE_REPOSITORY:-drbree82/hermes-memory-palace}
ref=${MEMORY_PALACE_REF:-main}
source_dir=${MEMORY_PALACE_SOURCE_DIR:-}
configure_hermes=${MEMORY_PALACE_CONFIGURE_HERMES:-1}

fail() {
    printf 'memory-palace install: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

case "$(uname -s)" in
    Linux|Darwin) ;;
    *) fail "this release requires a Unix-like Hermes host" ;;
esac

: "${HOME:?HOME must be set}"
hermes_home=${HERMES_HOME:-"$HOME/.hermes"}
palace_home=$hermes_home/memory-palace
command_dir=${MEMORY_PALACE_BIN_DIR:-"$HOME/.local/bin"}
temporary_dir=

cleanup() {
    if [ -n "$temporary_dir" ] && [ -d "$temporary_dir" ]; then
        rm -rf "$temporary_dir"
    fi
}
trap cleanup EXIT HUP INT TERM

require_command cargo
require_command install

if [ -z "$source_dir" ]; then
    require_command curl
    require_command tar
    temporary_dir=$(mktemp -d "${TMPDIR:-/tmp}/memory-palace-install.XXXXXX")
    source_dir=$temporary_dir/source
    mkdir -p "$source_dir"
    archive_url=https://github.com/$repository/archive/$ref.tar.gz
    printf 'Downloading %s at %s...\n' "$repository" "$ref"
    curl --fail --silent --show-error --location \
        --proto '=https' --tlsv1.2 \
        "$archive_url" |
        tar -xzf - --strip-components=1 -C "$source_dir"
fi

[ -f "$source_dir/Cargo.lock" ] || fail "Cargo.lock not found in $source_dir"
[ -d "$source_dir/adapters/hermes/memory_palace" ] || \
    fail "Hermes adapter not found in $source_dir"
[ -d "$source_dir/adapters/hermes/memory_palace_context" ] || \
    fail "Hermes context adapter not found in $source_dir"

printf 'Building the native binary...\n'
cargo build --locked --release --manifest-path "$source_dir/Cargo.toml"

if [ ! -d "$hermes_home" ]; then
    install -d -m 0700 "$hermes_home"
fi
install -d -m 0700 "$palace_home" "$palace_home/bin" "$palace_home/run" "$palace_home/log"
install -d -m 0755 "$command_dir" \
    "$hermes_home/plugins/memory-palace" \
    "$hermes_home/plugins/memory-palace-context"
install -m 0755 "$source_dir/target/release/memory-palace" \
    "$palace_home/bin/memory-palace"
install -m 0755 "$source_dir/target/release/memory-palace" \
    "$command_dir/memory-palace"
install -m 0644 "$source_dir/adapters/hermes/memory_palace/__init__.py" \
    "$hermes_home/plugins/memory-palace/__init__.py"
install -m 0644 "$source_dir/adapters/hermes/memory_palace/client.py" \
    "$hermes_home/plugins/memory-palace/client.py"
install -m 0644 "$source_dir/adapters/hermes/memory_palace/plugin.yaml" \
    "$hermes_home/plugins/memory-palace/plugin.yaml"
install -m 0644 "$source_dir/adapters/hermes/memory_palace_context/__init__.py" \
    "$hermes_home/plugins/memory-palace-context/__init__.py"
install -m 0644 "$source_dir/adapters/hermes/memory_palace_context/client.py" \
    "$hermes_home/plugins/memory-palace-context/client.py"
install -m 0644 "$source_dir/adapters/hermes/memory_palace_context/plugin.yaml" \
    "$hermes_home/plugins/memory-palace-context/plugin.yaml"

"$palace_home/bin/memory-palace" --home "$palace_home" doctor

if [ "$configure_hermes" != "0" ] && command -v hermes >/dev/null 2>&1; then
    printf 'Enabling Memory Palace in Hermes...\n'
    HERMES_HOME="$hermes_home" hermes plugins enable \
        --no-allow-tool-override memory-palace
    HERMES_HOME="$hermes_home" hermes plugins enable \
        --no-allow-tool-override memory-palace-context
    HERMES_HOME="$hermes_home" hermes config set memory.provider memory-palace
    HERMES_HOME="$hermes_home" hermes config set context.engine memory-palace
fi

printf '\nMemory Palace installed for Hermes profile: %s\n' "$hermes_home"
printf 'CLI installed at: %s/memory-palace\n' "$command_dir"
if [ "$configure_hermes" = "0" ] || ! command -v hermes >/dev/null 2>&1; then
    printf '%s\n' 'Set memory.provider and context.engine to memory-palace in the Hermes configuration.'
else
    printf '%s\n' 'Hermes memory provider and context engine are enabled; the engine enforces durable compression checkpoints.'
fi

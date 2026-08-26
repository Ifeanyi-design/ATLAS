#!/bin/sh
set -eu
umask 077

repository=${MEMORY_PALACE_REPOSITORY:-drbree82/hermes-memory-palace}
ref=${MEMORY_PALACE_REF:-main}
source_dir=${MEMORY_PALACE_SOURCE_DIR:-}

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

printf 'Building the native binary...\n'
cargo build --locked --release --manifest-path "$source_dir/Cargo.toml"

if [ ! -d "$hermes_home" ]; then
    install -d -m 0700 "$hermes_home"
fi
install -d -m 0700 "$palace_home" "$palace_home/bin" "$palace_home/run" "$palace_home/log"
install -d -m 0755 "$command_dir" "$hermes_home/plugins/memory-palace"
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

"$palace_home/bin/memory-palace" --home "$palace_home" doctor

printf '\nMemory Palace installed for Hermes profile: %s\n' "$hermes_home"
printf 'CLI installed at: %s/memory-palace\n' "$command_dir"
printf '%s\n' 'Select memory-palace as memory.provider and enable compression.checkpoint_required in Hermes configuration.'

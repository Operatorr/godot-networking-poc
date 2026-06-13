#!/usr/bin/env bash
# Build the client GDExtension (sim_core + protocol codec, migration-spec D5/D6) and copy the
# artifact into the Godot project so exports need no Rust toolchain.
#
# Usage: ./scripts/build_client_ext.sh [--debug]
set -euo pipefail
cd "$(dirname "$0")/../rust"

PROFILE="release"
CARGO_FLAGS="--release"
if [[ "${1:-}" == "--debug" ]]; then
    PROFILE="debug"
    CARGO_FLAGS=""
fi

cargo build -p client_ext $CARGO_FLAGS

case "$(uname -s)" in
Darwin)
    mkdir -p ../client/bin/macos
    # rm first: overwriting in place keeps the old inode, and the kernel's cached
    # code-signature for it goes stale — dyld then SIGKILLs (Code Signature Invalid).
    rm -f ../client/bin/macos/libclient_ext.dylib
    cp "target/$PROFILE/libclient_ext.dylib" ../client/bin/macos/
    echo "→ client/bin/macos/libclient_ext.dylib ($PROFILE)"
    ;;
Linux)
    mkdir -p ../client/bin/linux
    cp "target/$PROFILE/libclient_ext.so" ../client/bin/linux/
    echo "→ client/bin/linux/libclient_ext.so ($PROFILE)"
    ;;
MINGW* | MSYS* | CYGWIN*)
    mkdir -p ../client/bin/windows
    cp "target/$PROFILE/client_ext.dll" ../client/bin/windows/
    echo "→ client/bin/windows/client_ext.dll ($PROFILE)"
    ;;
*)
    echo "unsupported platform: $(uname -s)" >&2
    exit 1
    ;;
esac

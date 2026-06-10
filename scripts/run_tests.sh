#!/bin/bash
# Run the headless GDScript regression tests (SceneTree scripts under
# client/scripts/test/). Each test prints "All ... tests passed" and exits 0 on
# success, non-zero on the first failed assertion.
#
# Usage: ./scripts/run_tests.sh

set -u

cd "$(dirname "$0")/../client"

# Resolve a Godot binary (PATH first, then common install locations).
GODOT_BIN="${GODOT_BIN:-}"
if [ -z "$GODOT_BIN" ]; then
	if command -v godot &> /dev/null; then
		GODOT_BIN="godot"
	elif [ -x "$HOME/bin/godot" ]; then
		GODOT_BIN="$HOME/bin/godot"
	else
		echo "Error: Godot not found. Add it to PATH or set GODOT_BIN." >&2
		exit 127
	fi
fi

# Refresh the global class-name cache so class_name scripts resolve under --script.
"$GODOT_BIN" --headless --import . > /dev/null 2>&1 || true

# SceneTree test scripts to run (paths relative to client/).
TESTS=(
	"scripts/test/hit_authority_test.gd"
	"scripts/test/packet_color_test.gd"
)

FAILED=0
for test in "${TESTS[@]}"; do
	echo "=== Running $test ==="
	# Autoloads emit incidental boot noise (e.g. a failed server bind); the test's
	# own pass/fail line and exit code are authoritative.
	if "$GODOT_BIN" --headless --path . --script "$test"; then
		echo "PASS: $test"
	else
		echo "FAIL: $test"
		FAILED=1
	fi
	echo
done

if [ "$FAILED" -ne 0 ]; then
	echo "Some GDScript tests FAILED."
	exit 1
fi

echo "All GDScript tests passed."

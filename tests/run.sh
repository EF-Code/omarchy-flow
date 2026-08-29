#!/usr/bin/env bash
# Omarchy Flow — Full Test Suite & Quality Gate Runner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TEST_XDG_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/omarchy-flow-tests.XXXXXX")"
TEST_CONFIG_HOME="$TEST_XDG_ROOT/config"
TEST_RUNTIME_DIR="$TEST_XDG_ROOT/runtime"
TEST_STATE_HOME="$TEST_XDG_ROOT/state"
mkdir -m 700 "$TEST_CONFIG_HOME" "$TEST_RUNTIME_DIR" "$TEST_STATE_HOME"
cleanup() {
  rm -rf -- "$TEST_XDG_ROOT"
}
trap cleanup EXIT
export XDG_CONFIG_HOME="$TEST_CONFIG_HOME"
export XDG_RUNTIME_DIR="$TEST_RUNTIME_DIR"
export XDG_STATE_HOME="$TEST_STATE_HOME"

if [[ -n "${OMARCHY_FLOW_PYTHON:-}" && -x "$OMARCHY_FLOW_PYTHON" ]]; then
  PYTHON_BIN="$OMARCHY_FLOW_PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON_BIN="$VIRTUAL_ENV/bin/python"
elif [[ -x "$HOME/.venv/bin/python" ]]; then
  PYTHON_BIN="$HOME/.venv/bin/python"
elif [[ -x "$HOME/.local/share/venvs/default/bin/python" ]]; then
  PYTHON_BIN="$HOME/.local/share/venvs/default/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Error: Python 3 not found on system PATH." >&2
  exit 1
fi
export OMARCHY_FLOW_PYTHON="$PYTHON_BIN"

echo "=== 1. Validating Omarchy Plugin Manifest ==="
omarchy plugin validate .
echo "Manifest OK."

echo ""
echo "=== 2. Linting QML Components (qmllint) ==="
OMARCHY_SHELL_PATH="${OMARCHY_PATH:-/usr/share/omarchy}/shell"
qmllint -I "$OMARCHY_SHELL_PATH" BarWidget.qml SettingsView.qml FlowDropdown.qml Pill.qml Service.qml
echo "QML Lint OK."

echo ""
echo "=== 3. Running Backend Unit Tests ==="
"$PYTHON_BIN" tests/test_backend.py
echo "Unit tests OK."

echo ""
echo "=== 4. Testing CLI Dispatcher (flowctl) ==="
./scripts/flowctl help >/dev/null
./scripts/flowctl status >/dev/null
./scripts/flowctl list-models >/dev/null
echo "CLI Dispatcher OK."

echo ""
echo "=== 5. Syntax Compilation Checks ==="
bash -n scripts/flowctl tests/run.sh
"$PYTHON_BIN" -m py_compile scripts/gemini-dictate.py tests/test_backend.py
echo "Syntax checks OK."

echo ""
echo "=== 6. Verifying Repository Cleanliness & Portability ==="
# Check for unintended hardcoded user paths in source files
if rg -n '/home/[A-Za-z0-9._-]+' \
  BarWidget.qml Pill.qml Service.qml manifest.json scripts tests \
  --glob '*.qml' --glob '*.py' --glob '*.sh' --glob '*.json'; then
  echo "Error: Hardcoded developer home path found in core QML or manifest files!" >&2
  exit 1
fi
echo "Portability check OK."

echo ""
echo "=== 7. Shell Script Quality ==="
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=info scripts/flowctl tests/run.sh
  echo "ShellCheck OK."
else
  echo "ShellCheck not installed; skipped."
fi

echo ""
echo "All Omarchy Flow tests passed successfully! 🌊"

#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"
if [[ -n "${WASM_AGENT_PYTHON:-}" ]]; then
  python_command="$WASM_AGENT_PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
  python_command="$root/.venv/bin/python"
else
  python_command="$root/.venv/Scripts/python.exe"
fi
exec "$python_command" -m wasm_agent.cli collect "$@"

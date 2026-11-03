#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/../.." && pwd)"
cd -- "$root_dir"
if [[ -n "${WASM_AGENT_PYTHON:-}" ]]; then
  python_command="$WASM_AGENT_PYTHON"
elif [[ -x "$root_dir/.venv/bin/python" ]]; then
  python_command="$root_dir/.venv/bin/python"
else
  python_command="$root_dir/.venv/Scripts/python.exe"
fi
exec "$python_command" -m scripts.lab.run "$@"

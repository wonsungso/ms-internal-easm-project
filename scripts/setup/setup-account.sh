#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_command="${WASM_AGENT_PYTHON:-python3}"
exec "$python_command" "$script_dir/setup_account.py" "$@"

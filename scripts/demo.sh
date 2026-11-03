#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"
if [[ "${1:-}" != "--apply" ]]; then
  printf '%s\n' '관리자 전용 데모 배포입니다. 승인 후 bash scripts/demo.sh --apply를 사용하세요.' >&2
  exit 1
fi
python_command="${WASM_AGENT_PYTHON:-$root/.venv/bin/python}"
"$python_command" -m scripts.lab.run validate --prepare-providers
"$python_command" -m scripts.lab.run all --apply
"$python_command" -m scripts.lab.expand --apply
set +e
"$python_command" -m scripts.lab.run collect
status=$?
set -e
if [[ "$status" -ne 0 && "$status" -ne 2 ]]; then
  exit "$status"
fi
"$python_command" -m scripts.lab.summarize

#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"
apply=false
collect=false
for argument in "$@"; do
  case "$argument" in
    --apply) apply=true ;;
    --collect) collect=true ;;
    *) printf '지원하지 않는 인자: %s\n' "$argument" >&2; exit 1 ;;
  esac
done
if [[ "$apply" != true ]]; then
  printf '%s\n' '관리자 전용입니다. 승인 후 bash demo/run.sh --apply [--collect]를 사용하세요.' >&2
  exit 1
fi
if [[ -n "${WASM_AGENT_PYTHON:-}" ]]; then
  python_command="$WASM_AGENT_PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
  python_command="$root/.venv/bin/python"
else
  python_command="$root/.venv/Scripts/python.exe"
fi
"$python_command" -m demo.manage validate --prepare-providers
"$python_command" -m demo.manage deploy --apply
"$python_command" -m demo.agents --apply
if [[ "$collect" == true ]]; then
  set +e
  "$python_command" -m demo.manage collect
  status=$?
  set -e
  if [[ "$status" -ne 0 && "$status" -ne 2 ]]; then
    exit "$status"
  fi
  "$python_command" -m demo.diagnostics verify
fi

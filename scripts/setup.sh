#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/.." && pwd)"
python_command="${WASM_AGENT_PYTHON:-python3}"
command="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command" in
  login) mode="--login" ;;
  plan) mode="--dry-run" ;;
  apply) mode="--apply" ;;
  verify) mode="--verify" ;;
  help|-h|--help)
    printf '%s\n' \
      'Usage: bash scripts/setup.sh <login|plan|apply|verify> [options]' \
      'Default config: .wasm-agent/setup.json (no secrets).' \
      'Options: --config-file FILE, --cost-reader, --monitoring-reader,' \
      '  --log-analytics-reader, --security-reader, --certificate-path FILE.' \
      'login: human administrator device-code login; SP authentication is separate.' \
      'plan: no Azure calls. apply: explicit role changes. verify: read-only SP checks.'
    exit 0
    ;;
  *)
    printf 'Unknown command: %s\n' "$command" >&2
    exit 1
    ;;
esac

for argument in "$@"; do
  case "$argument" in
    --apply|--login|--verify|--dry-run|--what-if)
      printf 'Choose the mode with the subcommand, not %s.\n' "$argument" >&2
      exit 1
      ;;
  esac
done

exec "$python_command" "$script_dir/setup_account.py" \
  --config-file "$root_dir/.wasm-agent/setup.json" \
  --result-file "$root_dir/.wasm-agent/setup.json" "$mode" "$@"

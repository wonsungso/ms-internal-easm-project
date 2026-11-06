#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/.." && pwd)"
config_file="$script_dir/setup.json"
repository_mode=false
if [[ -f "$script_dir/verify_permissions.py" ]]; then
  config_file="$root_dir/.wasm-agent/setup.json"
  repository_mode=true
fi
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
  cleanup-plan|cleanup-apply) mode="" ;;
  help|-h|--help)
    printf '%s\n' \
      'Customer: bash setup.sh <login|plan|apply|cleanup-plan|cleanup-apply> [options]' \
      'MS repository: bash scripts/setup.sh <login|plan|apply|verify> [options]' \
      "Default config: $config_file (no secrets)." \
      'Defaults: Reader, Cost Management Reader, Log Analytics Reader, Security Reader,' \
      '  Foundry read-only DataActions, and the three required Graph application roles.' \
      'Options: --config-file FILE, --certificate-path FILE, --projects-file FILE.' \
      'login: human administrator device-code login; SP authentication is separate.' \
      'plan: no Azure calls. apply: explicit role changes. verify: read-only SP checks.' \
      'cleanup-plan: read-only deletion preview. cleanup-apply: delete only the recorded diagnostic identity.'
    exit 0
    ;;
  *)
    printf 'Unknown command: %s\n' "$command" >&2
    exit 1
    ;;
esac

if [[ "$command" == verify && "$repository_mode" == false ]]; then
  printf '%s\n' 'verify must run in the MS repository with the diagnostic certificate, not in the customer folder.' >&2
  exit 1
fi

for argument in "$@"; do
  case "$argument" in
    --apply|--login|--verify|--dry-run|--what-if)
      printf 'Choose the mode with the subcommand, not %s.\n' "$argument" >&2
      exit 1
      ;;
  esac
done

if [[ "$command" == cleanup-plan || "$command" == cleanup-apply ]]; then
  cleanup_options=()
  if [[ "$command" == cleanup-apply ]]; then
    cleanup_options+=(--apply)
  fi
  exec "$python_command" "$script_dir/cleanup_account.py" \
    --config-file "$config_file" --result-file "$(dirname -- "$config_file")/cleanup-result.json" \
    "${cleanup_options[@]}" "$@"
fi

exec "$python_command" "$script_dir/setup_account.py" \
  --config-file "$config_file" \
  --result-file "$config_file" "$mode" "$@"

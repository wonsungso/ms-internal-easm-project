#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"'
.venv/bin/python -m pip install -e ".[dev]"
mkdir -p output .wasm-agent/evidence
.venv/bin/wasm-agent --help
az version --output json
printf '%s\n' 'EASM 준비 완료. Azure 인증은 별도로 실행하세요.'

"""Resolve the MS diagnostic certificate path without reading private key contents."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_certificate_path(root: Path = ROOT, home: Path | None = None) -> Path:
    record = root / ".wasm-agent" / "certificate-path"
    if record.is_file():
        value = record.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError("저장된 인증서 경로가 비어 있습니다. Step 1 인증서를 확인하세요.")
        certificate = Path(value)
        if not certificate.is_absolute() or not certificate.is_file():
            raise ValueError("Step 1에 저장한 인증서 파일이 없습니다. 다른 인증서로 자동 대체하지 않습니다.")
        return certificate
    directory = (home or Path.home()) / ".config" / "wasm-agent"
    candidates = [path for path in directory.glob("auth-*/diagnostic.pem") if path.is_file()]
    if not candidates:
        raise ValueError("진단 인증서가 없습니다. 같은 Codespaces에서 Step 1을 먼저 수행하세요.")
    if len(candidates) != 1:
        raise ValueError("인증서가 여러 개이며 Step 1 경로 기록이 없습니다. 임의로 선택하지 않습니다.")
    certificate = candidates[0].resolve()
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(str(certificate) + "\n", encoding="utf-8")
    return certificate


if __name__ == "__main__":
    try:
        print(resolve_certificate_path())
    except (OSError, ValueError) as error:
        print(f"인증서 경로 확인 실패: {error}", file=sys.stderr)
        raise SystemExit(1) from error

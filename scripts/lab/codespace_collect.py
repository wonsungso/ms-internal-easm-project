from __future__ import annotations

import argparse
import base64
import json
import re
import shlex
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import yaml

from scripts.lab.auth import TemporaryCertificate
from scripts.lab.run import ROOT, save
from wasm_agent.settings import load_yaml

WORKSPACE = "/workspaces/ms-internal-wasm-project"


def gh(*arguments: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["gh", *arguments], capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode not in allowed:
        raise RuntimeError(f"Codespaces 작업 실패: {arguments[0:2]}, exit={result.returncode}; 원문 비출력")
    return result


def run(codespace: str) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", codespace):
        raise ValueError("유효한 Codespace 이름이 필요합니다.")
    setup = json.loads((ROOT / ".wasm-agent" / "setup.json").read_text(encoding="utf-8"))
    lab = json.loads((ROOT / ".wasm-agent" / "demo" / "lab.json").read_text(encoding="utf-8"))
    settings = load_yaml(ROOT / "config" / "config.yaml")
    settings.update({
        "tenant_id": setup["tenant_id"], "expected_principal_id": setup["principal_id"],
        "subscriptions": [],
        "evidence_dir": WORKSPACE + "/.wasm-agent/evidence",
        "projects": [{"subscription_id": setup["subscription_ids"][0],
                      "resource_id": lab["project_id"], "endpoint": lab["project_endpoint"]}],
    })
    for key in ("allowed_models_file", "criteria_file", "tag_conventions_file"):
        settings[key] = WORKSPACE + "/config/" + Path(settings[key]).name
    directory = gh("codespace", "ssh", "-c", codespace, "--",
                   "umask 077; mktemp -d /home/vscode/wasm-agent-auth-XXXXXXXX").stdout.strip()
    if not re.fullmatch(r"/home/vscode/wasm-agent-auth-[A-Za-z0-9]{8}", directory):
        raise RuntimeError("Codespace의 보호된 임시 경로를 확인할 수 없습니다.")
    remote_cleanup = False
    code = None
    try:
        with tempfile.TemporaryDirectory(prefix="wasm-agent-config-") as local:
            config = Path(local) / "collection.yaml"
            config.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
            with TemporaryCertificate(setup) as environment:
                try:
                    for source, name in [(Path(environment["AZURE_CLIENT_CERTIFICATE_PATH"]), "credential.pem"),
                                         (config, "collection.yaml")]:
                        gh("codespace", "cp", "-c", codespace, "--", "-O", str(source),
                           "remote:" + directory + "/" + name)
                    command = (
                        f"set -eu; chmod 600 {directory}/credential.pem {directory}/collection.yaml; "
                        f"cd {WORKSPACE}; set +e; env -u AZURE_CLIENT_SECRET -u AZURE_FEDERATED_TOKEN_FILE "
                        f"-u AZURE_CLIENT_CERTIFICATE_PASSWORD "
                        f"AZURE_TENANT_ID={shlex.quote(setup['tenant_id'])} "
                        f"AZURE_CLIENT_ID={shlex.quote(setup['client_id'])} "
                        f"AZURE_CLIENT_CERTIFICATE_PATH={directory}/credential.pem "
                        f".venv/bin/wasm-agent collect --config {directory}/collection.yaml "
                        "--all-subscriptions --output-dir output; "
                        'code=$?; printf "\\nWASM_COLLECTION_EXIT=%s\\n" "$code"; '
                        'test "$code" -eq 0 || test "$code" -eq 2'
                    )
                    result = gh("codespace", "ssh", "-c", codespace, "--", command)
                    marker = re.search(r"^WASM_COLLECTION_EXIT=([02])$", result.stdout, re.MULTILINE)
                    if marker is None:
                        raise RuntimeError("Codespaces 수집 종료 상태를 확인하지 못했습니다.")
                    code = int(marker[1])
                    print(result.stdout, end="")
                finally:
                    gh("codespace", "ssh", "-c", codespace, "--",
                       f"rm -f {directory}/credential.pem {directory}/collection.yaml; rmdir {directory}")
                    remote_cleanup = True
        destination = ROOT / "output"
        destination.mkdir(exist_ok=True)
        result = gh("codespace", "ssh", "-c", codespace, "--", f"base64 {WORKSPACE}/output/results.zip")
        payload = base64.b64decode("".join(result.stdout.split()), validate=True)
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != {
                "report.html", "report.xlsx", "data.json",
            }:
                raise RuntimeError("Codespaces에서 받은 ZIP의 무결성/구성 검사 실패")
            for name in ("report.html", "report.xlsx"):
                (destination / name).write_bytes(archive.read(name))
        (destination / "results.zip").write_bytes(payload)
        save(ROOT / ".wasm-agent" / "demo" / "codespace-e2e-verification.json", {
            "codespace": codespace, "collection_exit_code": code, "all_subscriptions": True,
            "remote_private_key_cleaned": remote_cleanup, "temporary_certificate_cleaned": True,
            "archives": ["results.zip"], "administrator_collection_fallback": False,
        })
    finally:
        if not remote_cleanup:
            gh("codespace", "ssh", "-c", codespace, "--",
               f"rm -f {directory}/credential.pem {directory}/collection.yaml; rmdir {directory}")


def main() -> int:
    parser = argparse.ArgumentParser(description="승인된 단기 인증서로 Codespaces 실제 진단 및 인증 재료 정리")
    parser.add_argument("--codespace", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        parser.error("인증서 전달에는 승인 확인 --apply가 필요합니다.")
    run(args.codespace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

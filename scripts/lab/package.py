from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path


def build_linux_package(root: Path) -> Path:
    dependencies = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["optional-dependencies"]["sample"]
    archive = root / ".wasm-agent" / "demo" / "langchain-sample.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    requirements_text = "\n".join(dependencies) + "\n"
    sources = {
        path.name: path for path in (root / "samples" / "langchain").iterdir()
        if path.is_file() and path.suffix in (".py", ".json", ".html")
    }
    if archive.is_file():
        with zipfile.ZipFile(archive) as existing:
            names = existing.namelist()
            if (
                {"app.py", "requirements.txt", ".deployment"} <= set(names)
                and existing.read("requirements.txt").decode().replace("\r\n", "\n") == requirements_text
                and existing.read(".deployment") == b"[config]\nSCM_DO_BUILD_DURING_DEPLOYMENT = false\n"
                and any(name.endswith(".so") for name in names)
                and not any(name.endswith(".pyd") for name in names)
                and existing.testzip() is None
            ):
                if all(
                    name in names and existing.read(name) == path.read_bytes()
                    for name, path in sources.items()
                ):
                    print("검증된 CPython 3.11 Linux 패키지 재사용", flush=True)
                    return archive
                with tempfile.TemporaryDirectory(prefix="seagent-repack-") as directory:
                    refreshed = Path(directory) / "sample.zip"
                    with zipfile.ZipFile(refreshed, "w", zipfile.ZIP_DEFLATED) as bundle:
                        for item in existing.infolist():
                            if item.filename.startswith(".python_packages/") or item.filename in (
                                ".deployment", "requirements.txt",
                            ):
                                bundle.writestr(item, existing.read(item))
                        for name, path in sources.items():
                            bundle.write(path, name)
                    existing.close()
                    refreshed.replace(archive)
                print("검증된 Linux 의존성은 유지하고 변경한 챗봇 소스만 다시 패키징", flush=True)
                return archive
        print("패키지 입력이 변경되어 Linux 의존성을 다시 준비합니다.", flush=True)
    with tempfile.TemporaryDirectory(prefix="seagent-wheel-") as directory:
        temporary = Path(directory)
        requirements = temporary / "requirements.txt"
        requirements.write_text(requirements_text, encoding="utf-8")
        packages = temporary / "packages"
        print("Python 3.11 Linux wheel 사전 패키징: 원격 Oryx 플랫폼 설치에 의존하지 않음", flush=True)
        completed = subprocess.run([
            sys.executable, "-m", "pip", "install", "--target", str(packages),
            "--platform", "manylinux_2_28_x86_64",
            "--platform", "manylinux_2_17_x86_64",
            "--platform", "manylinux2014_x86_64",
            "--python-version", "3.11", "--implementation", "cp", "--abi", "cp311",
            "--only-binary=:all:", "--no-compile", "-r", str(requirements),
        ], capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError("Linux wheel 의존성 사전 패키징 실패. pip 원문은 비밀 보호를 위해 출력하지 않음.")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, path in sources.items():
                bundle.write(path, name)
            bundle.write(requirements, "requirements.txt")
            bundle.writestr(".deployment", "[config]\nSCM_DO_BUILD_DURING_DEPLOYMENT = false\n")
            for path in packages.rglob("*"):
                if path.is_file():
                    destination = Path(".python_packages") / "lib" / "site-packages" / path.relative_to(packages)
                    bundle.write(path, destination.as_posix())
    return archive

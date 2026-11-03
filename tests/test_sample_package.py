from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.lab.package import build_linux_package


def test_source_only_repack_reuses_verified_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "samples"
    source.mkdir(parents=True)
    (source / "app.py").write_text("new chatbot source", encoding="utf-8")
    (source / "chat.html").write_text("new chat form", encoding="utf-8")
    (source / "catalog.json").write_text("[]", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project.optional-dependencies]\nsample = ["fixture==1"]\n', encoding="utf-8",
    )
    output = tmp_path / ".wasm-agent" / "demo"
    output.mkdir(parents=True)
    archive = output / "langchain-sample.zip"
    native = ".python_packages/lib/site-packages/native.so"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("app.py", "old health source")
        bundle.writestr("requirements.txt", "fixture==1\n")
        bundle.writestr(".deployment", "[config]\nSCM_DO_BUILD_DURING_DEPLOYMENT = false\n")
        bundle.writestr(native, b"\x7fELF fixture")
    with patch("scripts.lab.package.subprocess.run", side_effect=AssertionError("no reinstall")):
        assert build_linux_package(tmp_path) == archive
        assert build_linux_package(tmp_path) == archive
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read("app.py") == (source / "app.py").read_bytes()
        assert bundle.read("chat.html") == (source / "chat.html").read_bytes()
        assert bundle.read(native) == b"\x7fELF fixture"
        assert bundle.testzip() is None

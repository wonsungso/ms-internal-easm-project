from __future__ import annotations

import ast
import hashlib
import re
import shutil
from pathlib import Path

import pytest

from scripts import convert_sources as convert

SOURCE = Path(__file__).parents[1] / "docs" / "source"
SOURCE_AVAILABLE = bool(list(SOURCE.glob("*.docx"))) and bool(list(SOURCE.glob("*.xlsx")))

@pytest.mark.skipif(not SOURCE_AVAILABLE, reason="원문 검사는 승인된 원본 자료를 로컬로 제공한 경우에만 실행")
def test_source_criteria_exactly_twenty_and_unchanged_originals() -> None:
    source = Path(__file__).parents[1] / "docs" / "source"
    word = next(source.glob("*.docx"))
    workbook = next(source.glob("*.xlsx"))
    original_hashes = {p: hashlib.sha256(p.read_bytes()).digest() for p in (word, workbook)}
    _, tables = convert.read_word(word)
    _, sheets = convert.read_workbook(workbook)
    scope = convert.build_scope(word.name, tables, sheets)
    rows = [line for line in scope.splitlines() if re.match(r"\| [A-Z]{2}-SY-\d{2} \|", line)]
    assert len(rows) == 20
    assert sum("| in_scope |" in row for row in rows) == 2
    assert sum("| partial |" in row for row in rows) == 4
    assert sum("| out_of_scope |" in row for row in rows) == 14
    assert all(hashlib.sha256(p.read_bytes()).digest() == original_hashes[p] for p in original_hashes)


def test_unknown_source_structure_is_not_inferred() -> None:
    with pytest.raises(ValueError, match="Unexpected"):
        convert.build_scope("unreadable.docx", [], {})


def test_markdown_preserves_table_and_escapes_cells() -> None:
    text = convert.markdown_table([["first", "second"], ["a|b", "line1\nline2"]])
    assert "a&#124;b" in text
    assert "line1<br>line2" in text
    assert "| --- | --- |" in text


@pytest.mark.skipif(not SOURCE_AVAILABLE, reason="원문 검사는 승인된 원본 자료를 로컬로 제공한 경우에만 실행")
def test_conversion_normalizes_punctuation_and_preserves_originals(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "docs" / "source"
    for extension in ("*.docx", "*.xlsx"):
        original = next(source.glob(extension))
        shutil.copyfile(original, tmp_path / original.name)
    original_text = "sample " + chr(0x2014) + " text"
    original_file = tmp_path / "notes.txt"
    original_file.write_text(original_text, encoding="utf-8")
    outputs = convert.convert(tmp_path, tmp_path / "scope.md")
    assert original_file.read_text(encoding="utf-8") == original_text
    assert (tmp_path / "notes.txt.md").read_text(encoding="utf-8").endswith("sample - text\n")
    assert all(chr(0x2014) not in path.read_text(encoding="utf-8") for path in outputs)


def test_authored_documents_and_scripts_use_ascii_hyphens() -> None:
    root = Path(__file__).parents[1]
    extensions = {".md", ".txt", ".py", ".sh", ".ps1", ".json", ".yaml", ".yml", ".toml"}
    files = [path for path in root.iterdir() if path.is_file()]
    for directory in ("docs", "scripts", "tests", "config", ".github", "src", "demo"):
        files.extend((root / directory).rglob("*"))
    violations = []
    for path in files:
        if not path.is_file() or path.suffix not in extensions:
            continue
        if path.is_relative_to(root / "docs" / "source") and path.suffix != ".md":
            continue
        if chr(0x2014) in path.read_text(encoding="utf-8-sig"):
            violations.append(str(path.relative_to(root)))
    assert not violations, f"Use ASCII hyphens in: {violations}"


def test_flat_collector_layout_keeps_administrator_code_separate() -> None:
    root = Path(__file__).parents[1]
    package = root / "src" / "wasm_agent"
    assert not [path for path in package.iterdir() if path.is_dir() and path.name != "__pycache__"]
    assert (root / "scripts" / "setup_account.py").is_file()
    assert not (root / "scripts" / "setup").exists()
    assert (root / "demo" / "app.py").is_file()
    assert not (root / "scripts" / "lab").exists()
    assert not (root / "samples").exists()
    assert not (root / "infra").exists()
    assert not (root / "config" / "lab.yaml").exists()
    assert (root / "config" / "manual_agents.csv").is_file()
    assert not (root / "templates").exists()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(name.split(".")[0] in {"scripts", "demo"} for name in names), path.name


def test_resource_templates_and_collectors_use_current_brand() -> None:
    root = Path(__file__).parents[1]
    extensions = {".py", ".bicep", ".yaml", ".json", ".sh", ".html"}
    for directory in ("src", "scripts", "demo", "config", ".devcontainer", ".github"):
        for path in (root / directory).rglob("*"):
            if path.is_file() and path.suffix in extensions:
                assert "se" + "agent" not in path.read_text(encoding="utf-8-sig").lower(), path

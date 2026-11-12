from __future__ import annotations

from pathlib import Path

import pytest

from scripts.certificate_path import resolve_certificate_path


def certificate(home: Path, name: str) -> Path:
    path = home / ".config" / "easm-agent" / name / "diagnostic.pem"
    path.parent.mkdir(parents=True)
    path.write_text("test-only-certificate-placeholder", encoding="utf-8")
    return path


def test_single_existing_certificate_is_selected_and_recorded_without_reading_it(tmp_path: Path) -> None:
    home, root = tmp_path / "home", tmp_path / "repo"
    expected = certificate(home, "auth-one")
    assert resolve_certificate_path(root, home) == expected
    assert (root / ".easm-agent" / "certificate-path").read_text(encoding="utf-8").strip() == str(expected)
    assert expected.read_text(encoding="utf-8") == "test-only-certificate-placeholder"


def test_recorded_certificate_is_reused_even_if_a_newer_one_exists(tmp_path: Path) -> None:
    home, root = tmp_path / "home", tmp_path / "repo"
    expected = certificate(home, "auth-one")
    resolve_certificate_path(root, home)
    certificate(home, "auth-two")
    assert resolve_certificate_path(root, home) == expected


def test_multiple_candidates_are_not_guessed(tmp_path: Path) -> None:
    home, root = tmp_path / "home", tmp_path / "repo"
    certificate(home, "auth-one")
    certificate(home, "auth-two")
    with pytest.raises(ValueError, match="여러 개"):
        resolve_certificate_path(root, home)
    assert not (root / ".easm-agent" / "certificate-path").exists()


def test_missing_certificate_is_an_explicit_failure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="인증서가 없습니다"):
        resolve_certificate_path(tmp_path / "repo", tmp_path / "home")


@pytest.mark.parametrize("recorded", ["", "relative.pem", "/missing/diagnostic.pem"])
def test_invalid_record_does_not_fall_back_to_another_certificate(tmp_path: Path, recorded: str) -> None:
    home, root = tmp_path / "home", tmp_path / "repo"
    certificate(home, "auth-other")
    record = root / ".easm-agent" / "certificate-path"
    record.parent.mkdir(parents=True)
    record.write_text(recorded, encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_certificate_path(root, home)

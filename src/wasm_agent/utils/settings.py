from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: str
    resource_id: str
    endpoint: str


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str | None = None
    expected_principal_id: str | None = None
    subscriptions: list[str] = Field(default_factory=list)
    workers: int = Field(default=3, ge=1, le=16)
    evidence_dir: Path = Path("evidence")
    foundry_profile: Literal["agents_v1", "classic_v1"] = "agents_v1"
    projects: list[ProjectSettings] = Field(default_factory=list)
    manual_agents: Path | None = None
    allowed_models_file: Path = Path("allowed_models.yaml")
    criteria_file: Path = Path("criteria.yaml")
    tag_conventions_file: Path = Path("tag_conventions.yaml")
    policy_facts: dict[str, Any] = Field(default_factory=dict)
    interview_levels: dict[str, float] = Field(default_factory=dict)
    monitor: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ids(self) -> Settings:
        for field in ("tenant_id", "expected_principal_id"):
            if value := getattr(self, field):
                setattr(self, field, str(uuid.UUID(value)))
        self.subscriptions = list(dict.fromkeys(str(uuid.UUID(sid)) for sid in self.subscriptions))
        if any(not 1 <= value <= 5 for value in self.interview_levels.values()):
            raise ValueError("Interview levels must be between 1 and 5")
        return self


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: YAML object is required")
    return value


def load_settings(path: Path) -> Settings:
    settings = Settings.model_validate(load_yaml(path))
    for field in ("allowed_models_file", "criteria_file", "tag_conventions_file"):
        value = getattr(settings, field)
        if not value.is_absolute():
            setattr(settings, field, path.resolve().parent / value)
    return settings

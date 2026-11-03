from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from wasm_agent.models import Collection


class Collector(Protocol):
    required_roles: tuple[str, ...]

    def discover(self, subscriptions: Sequence[str]) -> Collection: ...

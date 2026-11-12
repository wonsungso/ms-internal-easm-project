from pathlib import Path


def state_path(root: Path, *parts: str) -> Path:
    return root.joinpath(".easm-agent", *parts)

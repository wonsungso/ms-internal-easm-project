"""평가기준과 확인 증적은 패키지 기준 파일에서 읽는다."""

from wasm_agent.models import load_criteria
from wasm_agent.proposals import TITLES

LEVELS: dict[str, tuple[str, ...]] = {
    code: (*entry["levels"].values(), entry["evidence"])
    for code, entry in load_criteria()["items"].items() if code in TITLES
}

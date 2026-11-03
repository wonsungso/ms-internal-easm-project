from unittest.mock import Mock, patch

import pytest

from scripts.lab.summarize import ready_health


def test_final_health_waits_for_real_json_after_restart() -> None:
    old = Mock(status_code=503, headers={"Content-Type": "text/html"})
    ready = Mock(status_code=200, headers={"Content-Type": "application/json"})
    ready.json.return_value = {"status": "ready", "sample_revision": "chatbot-v2"}
    with patch("scripts.lab.summarize.requests.get", side_effect=[old, ready]), patch(
        "scripts.lab.summarize.time.sleep",
    ):
        assert ready_health("https://example.test/health")["status"] == "ready"
    old.json.assert_not_called()
    old.close.assert_called_once()
    ready.close.assert_called_once()


def test_final_health_does_not_hide_authentication_failure() -> None:
    denied = Mock(status_code=403)
    with patch("scripts.lab.summarize.requests.get", return_value=denied), pytest.raises(
        RuntimeError, match="403",
    ):
        ready_health("https://example.test/health")

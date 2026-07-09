from pathlib import Path

import pytest

from ai_factory import safety
from ai_factory.verify import run_verification


def test_degraded_when_no_commands(tmp_path: Path) -> None:
    result = run_verification(tmp_path, {}, tmp_path / "verify")

    assert result.degraded is True
    assert result.passed is False
    assert result.results == ()
    assert not (tmp_path / "verify").exists()


def test_passing_gate(tmp_path: Path) -> None:
    commands = {"test": {"command": "true", "source": "declared", "confidence": "high"}}

    result = run_verification(tmp_path, commands, tmp_path / "verify")

    assert result.degraded is False
    assert result.passed is True
    assert len(result.results) == 1
    assert result.results[0].key == "test"
    assert result.results[0].passed is True
    assert result.results[0].log_path.exists()


def test_failing_gate_stops_at_first_failure(tmp_path: Path) -> None:
    commands = {
        "install": {"command": "true", "source": "declared", "confidence": "high"},
        "test": {"command": "false", "source": "declared", "confidence": "high"},
        "build": {"command": "true", "source": "declared", "confidence": "high"},
    }

    result = run_verification(tmp_path, commands, tmp_path / "verify")

    assert result.degraded is False
    assert result.passed is False
    # install (passes) then test (fails); build never runs.
    assert [r.key for r in result.results] == ["install", "test"]
    assert result.results[0].passed is True
    assert result.results[1].passed is False


def test_denied_command_refuses_without_running_anything(tmp_path: Path) -> None:
    commands = {
        "test": {"command": "git reset --hard", "source": "declared", "confidence": "high"}
    }

    with pytest.raises(safety.DeniedCommandError):
        run_verification(tmp_path, commands, tmp_path / "verify")

    # Refused before execution: no log directory was even created.
    assert not (tmp_path / "verify").exists()


def test_denied_command_checked_before_any_earlier_safe_command_runs(tmp_path: Path) -> None:
    commands = {
        "install": {"command": "true", "source": "declared", "confidence": "high"},
        "test": {"command": "git push --force", "source": "declared", "confidence": "high"},
    }

    with pytest.raises(safety.DeniedCommandError):
        run_verification(tmp_path, commands, tmp_path / "verify")

    assert not (tmp_path / "verify").exists()

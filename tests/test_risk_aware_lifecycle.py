import json
from pathlib import Path

import pytest

from ai_factory import decision_gate, risk
from ai_factory.cli import main

_DEGRADED_PROFILE = {"commands": {}, "degraded": True}
_TESTED_PROFILE = {
    "commands": {"test": {"command": "pytest", "source": "inferred", "confidence": "medium"}},
    "degraded": False,
}


def _run(
    target: Path,
    state_dir: Path,
    task: str,
    backend: str = "fake",
    extra_args: list[str] | None = None,
) -> int:
    return main(
        [
            "run",
            str(target),
            task,
            "--backend",
            backend,
            "--state-dir",
            str(state_dir),
            *(extra_args or []),
        ]
    )


def _load_run_dir(state_dir: Path) -> Path:
    run_dirs = list((state_dir / "runs").iterdir())
    assert len(run_dirs) == 1
    return run_dirs[0]


def _load_run_metadata(state_dir: Path) -> dict:
    return json.loads((_load_run_dir(state_dir) / "metadata.json").read_text())


# --- risk.classify() -- pure function, deterministic --------------------------------


def test_classify_low_risk_no_domain_matched() -> None:
    level, reasons = risk.classify("fix a typo in the README", _TESTED_PROFILE)

    assert level == "low"
    assert reasons


def test_classify_is_deterministic() -> None:
    first = risk.classify("add login support with OAuth", _TESTED_PROFILE)
    second = risk.classify("add login support with OAuth", _TESTED_PROFILE)

    assert first == second


def test_classify_high_risk_domain_auth() -> None:
    level, reasons = risk.classify("add a new login flow using OAuth", _TESTED_PROFILE)

    assert level == "high"
    assert any("auth_authz" in reason for reason in reasons)


def test_classify_medium_risk_domain_broad_refactor() -> None:
    level, _ = risk.classify("refactor the module structure", _TESTED_PROFILE)

    assert level == "medium"


def test_classify_weak_verification_bumps_risk_when_domain_matched() -> None:
    with_tests, _ = risk.classify("refactor the module structure", _TESTED_PROFILE)
    without_tests, reasons = risk.classify("refactor the module structure", _DEGRADED_PROFILE)

    assert with_tests == "medium"
    assert without_tests == "high"
    assert any("weak or absent verification" in reason for reason in reasons)


def test_classify_domain_free_task_stays_low_even_without_verification() -> None:
    level, _ = risk.classify("fix a typo in the README", _DEGRADED_PROFILE)

    assert level == "low"


def test_classify_predicted_files_can_trigger_domain_match() -> None:
    level, reasons = risk.classify(
        "clean up some code", _TESTED_PROFILE, predicted_files=["migrations/0001_init.sql"]
    )

    assert level == "high"
    assert any("db_migrations" in reason for reason in reasons)


# --- decision_gate.decide() -- pure function, deterministic -------------------------


def test_gate_low_risk_continues() -> None:
    decision = decision_gate.decide("low")

    assert decision.should_implement
    assert decision.outcome_reason is None
    assert not decision.force_implement_used


def test_gate_medium_and_high_pause_by_default() -> None:
    for level in ("medium", "high"):
        decision = decision_gate.decide(level)
        assert not decision.should_implement
        assert decision.outcome_reason is not None


def test_gate_pause_after_plan_always_pauses_even_for_low_risk() -> None:
    decision = decision_gate.decide("low", pause_after_plan=True)

    assert not decision.should_implement
    assert "pause-after-plan" in decision.outcome_reason


def test_gate_force_implement_overrides_medium_and_high() -> None:
    decision = decision_gate.decide("high", force_implement=True)

    assert decision.should_implement
    assert decision.force_implement_used


def test_gate_auto_does_not_override_medium_or_high() -> None:
    decision = decision_gate.decide("high", auto=True)

    assert not decision.should_implement
    assert not decision.force_implement_used


# --- End-to-end via the CLI, real git + Fake Agent ----------------------------------


def test_low_risk_task_auto_continues_through_implement_and_verify(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir, "fix a typo in the README")

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)

    assert metadata["risk"]["level"] == "low"
    assert metadata["decision_gate"]["paused"] is False
    assert metadata["phases"]["implement"]["status"] == "succeeded"
    assert metadata["outcome"] in ("implemented_verified", "implemented_degraded")


def test_medium_or_high_risk_task_pauses_after_plan(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir, "add an OAuth login flow")

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)

    assert metadata["risk"]["level"] == "high"
    assert metadata["decision_gate"]["paused"] is True
    assert metadata["outcome"] == "planned"
    assert "risk classified" in metadata["outcome_reason"]
    assert metadata["phases"]["implement"]["status"] == "not_executed"
    assert metadata["phases"]["verify"]["status"] == "not_executed"

    plan_text = (_load_run_dir(state_dir) / "plan.md").read_text()
    assert "## 12. Risk Assessment" in plan_text

    report_text = (_load_run_dir(state_dir) / "report.md").read_text()
    assert "Risk Assessment" in report_text
    assert "paused" in report_text


def test_pause_after_plan_flag_always_pauses_low_risk_task(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(
        git_repo,
        state_dir,
        "fix a typo in the README",
        extra_args=["--pause-after-plan"],
    )

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)

    assert metadata["risk"]["level"] == "low"
    assert metadata["decision_gate"]["paused"] is True
    assert metadata["outcome"] == "planned"
    assert "pause-after-plan" in metadata["outcome_reason"]


def test_force_implement_continues_despite_high_risk_and_is_recorded(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(
        git_repo,
        state_dir,
        "add an OAuth login flow",
        extra_args=["--force-implement"],
    )

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)

    assert metadata["risk"]["level"] == "high"
    assert metadata["decision_gate"]["paused"] is False
    assert metadata["decision_gate"]["force_implement_used"] is True
    assert metadata["decision_gate"]["flags"]["force_implement"] is True
    assert metadata["phases"]["implement"]["status"] == "succeeded"
    assert metadata["outcome"] in ("implemented_verified", "implemented_degraded")


def test_auto_flag_does_not_override_medium_or_high_risk(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(
        git_repo,
        state_dir,
        "add an OAuth login flow",
        extra_args=["--auto"],
    )

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)

    assert metadata["decision_gate"]["paused"] is True
    assert metadata["outcome"] == "planned"


def test_risk_override_flag_is_honored_and_recorded(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(
        git_repo,
        state_dir,
        "fix a typo in the README",
        extra_args=["--risk", "high"],
    )

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)

    assert metadata["risk"]["level"] == "high"
    assert metadata["risk"]["overridden_by_user"] is True
    assert metadata["decision_gate"]["paused"] is True
    assert metadata["decision_gate"]["flags"]["risk_override"] == "high"


def test_invalid_risk_override_is_refused(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    # argparse rejects the choice before the Factory ever runs.
    with pytest.raises(SystemExit) as exc_info:
        _run(
            git_repo,
            state_dir,
            "fix a typo",
            extra_args=["--risk", "critical"],
        )

    assert exc_info.value.code == 2


def test_risk_recorded_in_metadata_for_every_run(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    _run(git_repo, state_dir, "fix a typo in the README")

    metadata = _load_run_metadata(state_dir)
    risk_block = metadata["risk"]
    assert set(risk_block) == {"level", "reasons", "auto_continue_allowed", "overridden_by_user"}
    assert risk_block["level"] in ("low", "medium", "high")

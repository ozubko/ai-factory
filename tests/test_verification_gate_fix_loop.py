import json
import subprocess
from pathlib import Path

import pytest

import ai_factory.profiling as profiling_module
from ai_factory.cli import main


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _run(target: Path, state_dir: Path, task: str = "add a fake change") -> int:
    return main(
        [
            "run",
            str(target),
            task,
            "--backend",
            "fake",
            "--state-dir",
            str(state_dir),
        ]
    )


def _add_makefile(repo: Path, test_recipe: str) -> None:
    (repo / "Makefile").write_text(f"test:\n\t{test_recipe}\n")
    _git(["add", "Makefile"], cwd=repo)
    _git(["commit", "-m", "add Makefile"], cwd=repo)


def _load_run_metadata(state_dir: Path) -> dict:
    run_dirs = list((state_dir / "runs").iterdir())
    assert len(run_dirs) == 1
    return json.loads((run_dirs[0] / "metadata.json").read_text())


# --- Passing gate ------------------------------------------------------------


def test_passing_gate_yields_implemented_verified(git_repo: Path, tmp_path: Path) -> None:
    _add_makefile(git_repo, "true")
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)
    assert metadata["outcome"] == "implemented_verified"
    assert metadata["phases"]["verify"]["status"] == "succeeded"
    assert metadata["phases"]["verify"]["passed"] is True
    assert metadata["fix_loop"]["attempts"] == []

    log_path = Path(metadata["phases"]["verify"]["commands"][0]["log_path"])
    assert log_path.exists()
    assert log_path.parent.name == "attempt-0"
    assert log_path.parent.parent.name == "verify"

    report_text = (
        state_dir / "runs" / metadata["run_id"] / "report.md"
    ).read_text()
    assert "implemented_verified" in report_text
    assert "[PASS] test" in report_text


# --- No commands detected -> degraded, not refused ---------------------------


def test_no_commands_detected_yields_implemented_degraded_not_refused(
    git_repo: Path, tmp_path: Path
) -> None:
    # git_repo (from conftest) only has a README -- no ecosystem is detected.
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)
    assert metadata["outcome"] == "implemented_degraded"
    assert metadata["phases"]["verify"]["status"] == "skipped"
    assert metadata["phases"]["verify"]["degraded"] is True

    report_text = (
        state_dir / "runs" / metadata["run_id"] / "report.md"
    ).read_text()
    assert "degraded" in report_text.lower()


# --- Fix Loop: repairs a failing gate -----------------------------------------


def test_fix_loop_repairs_failing_gate(git_repo: Path, tmp_path: Path) -> None:
    # The implement phase alone only creates FAKE_AGENT_CHANGE.md; the gate
    # requires FAKE_AGENT_FIX.md, which only a `fix` phase attempt creates.
    _add_makefile(git_repo, "test -f FAKE_AGENT_FIX.md")
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 0
    metadata = _load_run_metadata(state_dir)
    assert metadata["outcome"] == "implemented_verified"
    assert metadata["phases"]["verify"]["status"] == "succeeded"
    assert metadata["phases"]["verify"]["passed"] is True

    attempts = metadata["fix_loop"]["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["verify"]["passed"] is True

    worktree_path = Path(metadata["worktree_path"])
    assert (worktree_path / "FAKE_AGENT_FIX.md").exists()

    report_text = (
        state_dir / "runs" / metadata["run_id"] / "report.md"
    ).read_text()
    assert "Fix Loop" in report_text
    assert "PASSED" in report_text


# --- Fix Loop: bounded, leaves it failing -------------------------------------


def test_fix_loop_exhausted_yields_implemented_unverified(git_repo: Path, tmp_path: Path) -> None:
    # Nothing the Fake Agent ever writes satisfies this -- the gate stays red
    # through every Fix Loop attempt.
    _add_makefile(git_repo, "test -f NEVER_CREATED.md")
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 1
    metadata = _load_run_metadata(state_dir)
    assert metadata["outcome"] == "implemented_unverified"
    assert metadata["phases"]["verify"]["status"] == "failed"
    assert metadata["phases"]["verify"]["passed"] is False

    attempts = metadata["fix_loop"]["attempts"]
    assert len(attempts) == metadata["fix_loop"]["max_attempts"] == 2
    assert all(attempt["verify"]["passed"] is False for attempt in attempts)

    report_text = (
        state_dir / "runs" / metadata["run_id"] / "report.md"
    ).read_text()
    assert "implemented_unverified" in report_text
    assert "still failing" in report_text


# --- Implement failure skips the gate entirely --------------------------------


def test_implement_failure_skips_verification_gate(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_factory.backend.subprocess_backend as backend_module
    from ai_factory.backend.base import AgentResult

    def _always_fail(self, request):  # type: ignore[no-untyped-def]
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        if request.phase == "plan":
            # A well-behaved plan phase, so the Run reaches (and fails at)
            # implement rather than halting earlier on a Contract Violation.
            request.output_path.write_text("plan placeholder\n")
            return AgentResult(
                exit_code=0,
                stdout_path=request.output_path,
                stderr_path=request.output_path,
                output_path=request.output_path,
                summary="plan placeholder",
            )
        request.output_path.write_text("boom\n")
        return AgentResult(
            exit_code=1,
            stdout_path=request.output_path,
            stderr_path=request.output_path,
            output_path=request.output_path,
            summary="boom",
        )

    build_profile_calls: list[Path] = []
    real_build_profile = profiling_module.build_profile

    def _counting_build_profile(repo: Path) -> dict:
        build_profile_calls.append(repo)
        return real_build_profile(repo)

    monkeypatch.setattr(backend_module.SubprocessBackend, "run", _always_fail)
    monkeypatch.setattr(profiling_module, "build_profile", _counting_build_profile)

    state_dir = tmp_path / "state"
    exit_code = _run(git_repo, state_dir)

    assert exit_code == 1
    metadata = _load_run_metadata(state_dir)
    assert metadata["outcome"] == "failed"
    assert metadata["phases"]["verify"]["status"] == "not_executed"
    # The Repo Profile is built exactly once, up front (needed by the plan
    # Phase's prompt) -- implement failing afterward must not trigger a
    # redundant re-profiling.
    assert len(build_profile_calls) == 1


# --- Deny-listed verification command refuses the run -------------------------


def test_denylisted_verification_command_refuses_run(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_profile(repo: Path) -> dict:
        return {
            "target_repo": str(repo),
            "ecosystem": "test-fixture",
            "degraded": False,
            "commands": {
                "test": {"command": "git reset --hard", "source": "declared", "confidence": "high"}
            },
            "instructions": [],
            "secrets_detected": [],
            "secret_values_included": False,
        }

    monkeypatch.setattr(profiling_module, "build_profile", _fake_profile)

    state_dir = tmp_path / "state"
    exit_code = _run(git_repo, state_dir)

    assert exit_code == 1
    metadata = _load_run_metadata(state_dir)
    assert metadata["outcome"] == "failed"
    assert "Deny-list" in metadata["outcome_reason"]

    run_dir = state_dir / "runs" / metadata["run_id"]
    assert not (run_dir / "verify").exists()

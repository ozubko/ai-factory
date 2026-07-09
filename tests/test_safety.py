import pytest

from ai_factory import safety


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .",
        "rm -fr /tmp/whatever",
        "git reset --hard",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git clean -df",
        "git push",
        "git push --force origin main",
        "git branch -D some-branch",
        "docker system prune -f",
        "dropdb mydb",
        "terraform apply",
        "kubectl delete pod mypod",
    ],
)
def test_check_command_refuses_denied_patterns(command: str) -> None:
    with pytest.raises(safety.DeniedCommandError):
        safety.check_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "make test",
        "npm test",
        "npm install",
        "ruff check .",
        "mypy .",
        "python -m build",
    ],
)
def test_check_command_allows_safe_commands(command: str) -> None:
    safety.check_command(command)  # must not raise


def test_check_command_is_deterministic() -> None:
    assert safety.check_command("pytest") == safety.check_command("pytest") is None
    with pytest.raises(safety.DeniedCommandError):
        safety.check_command("git reset --hard")
    with pytest.raises(safety.DeniedCommandError):
        safety.check_command("git reset --hard")

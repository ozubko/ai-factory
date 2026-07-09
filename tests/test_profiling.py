import json
from pathlib import Path

from ai_factory.cli import main
from ai_factory.profiling import build_profile


def test_python_ecosystem_detected_with_declared_and_inferred_commands(tmp_path: Path) -> None:
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"x\"\n"
        "[build-system]\nrequires = []\n"
        "[tool.pytest.ini_options]\n"
        "[tool.ruff]\n"
        "[tool.mypy]\n"
    )

    profile = build_profile(repo)

    assert profile["ecosystem"] == "python"
    assert profile["degraded"] is False
    commands = profile["commands"]
    assert commands["install"] == {
        "command": "pip install -e .",
        "source": "inferred",
        "confidence": "medium",
    }
    assert commands["test"]["command"] == "pytest"
    assert commands["test"]["source"] == "inferred"
    assert commands["lint"]["command"] == "ruff check ."
    assert commands["typecheck"]["command"] == "mypy ."
    assert commands["build"]["command"] == "python -m build"


def test_python_tox_is_declared_and_wins_over_pytest_inference(tmp_path: Path) -> None:
    repo = tmp_path / "python-tox-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = \"x\"\n")
    (repo / "tox.ini").write_text("[tox]\nenvlist = py311\n")
    (repo / "tests").mkdir()

    profile = build_profile(repo)

    assert profile["commands"]["test"] == {
        "command": "tox",
        "source": "declared",
        "confidence": "high",
    }


def test_node_ecosystem_detects_declared_scripts(tmp_path: Path) -> None:
    repo = tmp_path / "node-repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps(
            {
                "name": "x",
                "scripts": {
                    "test": "jest",
                    "lint": "eslint .",
                    "build": "tsc -p .",
                },
            }
        )
    )
    (repo / "tsconfig.json").write_text("{}")
    (repo / "yarn.lock").write_text("")

    profile = build_profile(repo)

    assert profile["ecosystem"] == "node"
    assert profile["degraded"] is False
    commands = profile["commands"]
    assert commands["install"] == {"command": "yarn install", "source": "inferred", "confidence": "medium"}
    assert commands["test"] == {"command": "yarn test", "source": "declared", "confidence": "high"}
    assert commands["lint"] == {"command": "yarn run lint", "source": "declared", "confidence": "high"}
    assert commands["build"] == {"command": "yarn run build", "source": "declared", "confidence": "high"}
    # No "typecheck" script declared, but tsconfig.json present -> inferred fallback.
    assert commands["typecheck"] == {"command": "tsc --noEmit", "source": "inferred", "confidence": "medium"}


def test_makefile_fallback_detects_declared_targets(tmp_path: Path) -> None:
    repo = tmp_path / "makefile-repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "install:\n\techo installing\n\ntest:\n\techo testing\n\nlint:\n\techo linting\n"
    )

    profile = build_profile(repo)

    assert profile["ecosystem"] == "makefile"
    assert profile["degraded"] is False
    commands = profile["commands"]
    assert commands["install"] == {"command": "make install", "source": "declared", "confidence": "high"}
    assert commands["test"] == {"command": "make test", "source": "declared", "confidence": "high"}
    assert commands["lint"] == {"command": "make lint", "source": "declared", "confidence": "high"}
    assert "build" not in commands
    assert "typecheck" not in commands


def test_unknown_ecosystem_is_degraded_with_empty_commands_and_no_crash(tmp_path: Path) -> None:
    repo = tmp_path / "mystery-repo"
    repo.mkdir()
    (repo / "notes.txt").write_text("nothing recognizable here\n")

    profile = build_profile(repo)

    assert profile["ecosystem"] == "unknown"
    assert profile["degraded"] is True
    assert profile["commands"] == {}


def test_instruction_files_are_discovered_labeled_and_truncation_recorded(tmp_path: Path) -> None:
    repo = tmp_path / "instructed-repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("short agent instructions\n")
    (repo / "README.md").write_text("x" * 5000)
    cursor_rules = repo / ".cursor" / "rules"
    cursor_rules.mkdir(parents=True)
    (cursor_rules / "style.mdc").write_text("use tabs\n")

    profile = build_profile(repo)

    by_path = {entry["path"]: entry for entry in profile["instructions"]}
    assert by_path["AGENTS.md"]["truncated"] is False
    assert by_path["AGENTS.md"]["content"] == "short agent instructions\n"
    assert by_path["README.md"]["truncated"] is True
    assert by_path["README.md"]["size_bytes"] == 5000
    assert len(by_path["README.md"]["content"]) == 4000
    assert by_path[".cursor/rules/style.mdc"]["content"] == "use tabs\n"


def test_secret_files_are_recorded_as_presence_only(tmp_path: Path) -> None:
    repo = tmp_path / "secretive-repo"
    repo.mkdir()
    secret_value = "SUPER_SECRET_TOKEN_VALUE"
    (repo / ".env").write_text(f"API_KEY={secret_value}\n")
    (repo / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----\nnotarealkey\n")

    profile = build_profile(repo)

    assert profile["secrets_detected"] == [".env", "id_rsa"]
    assert profile["secret_values_included"] is False

    serialized = json.dumps(profile)
    assert secret_value not in serialized
    assert "notarealkey" not in serialized


def test_secret_files_are_skipped_inside_ignored_directories(tmp_path: Path) -> None:
    repo = tmp_path / "node-modules-repo"
    repo.mkdir()
    nested = repo / "node_modules" / "some-pkg"
    nested.mkdir(parents=True)
    (nested / ".env").write_text("PKG_SECRET=irrelevant\n")

    profile = build_profile(repo)

    assert profile["secrets_detected"] == []


def test_detection_is_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "repeatable-repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    (repo / "AGENTS.md").write_text("be nice\n")
    (repo / ".env").write_text("X=1\n")

    first = build_profile(repo)
    second = build_profile(repo)

    assert first == second


def test_profile_command_prints_repo_profile_json(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "cli-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = \"x\"\n")

    exit_code = main(["profile", str(repo)])

    assert exit_code == 0
    output = capsys.readouterr().out
    profile = json.loads(output)
    assert profile["ecosystem"] == "python"
    assert profile["secret_values_included"] is False


def test_profile_command_refuses_non_directory_target(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    exit_code = main(["profile", str(missing)])

    assert exit_code == 1

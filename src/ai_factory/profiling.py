"""Deterministic Repo Profile: ecosystem/command detection, Repository Instructions
discovery, and secret-file presence recording (CONTEXT.md: Repo Profile, Ecosystem,
Repository Instructions; ADR-0005, ADR-0007, ADR-0010).

No model call, ever. The same Target Repo always produces the same profile: command
detection follows the extensible ecosystem registry below (Python, Node/TypeScript,
Makefile fallback), and every secret-file check reads a filename only — never a
file's contents — so secret values can never reach `profile.json`.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

# Repository Instructions are surfaced into prompts (ADR-0010) but are size-capped
# here so a huge README can't blow up a Prompt Bundle; truncation is recorded rather
# than silently applied.
MAX_INSTRUCTION_CHARS = 4000

INSTRUCTION_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules",
    ".github/copilot-instructions.md",
    "CONTRIBUTING.md",
    "README.md",
)

# Filenames only — contents are never read for these (ADR-0007: presence, not value).
SECRET_FILENAME_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_dsa",
    "credentials.json",
    ".npmrc",
    ".pypirc",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
)

IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        "dist",
        "build",
    }
)

COMMAND_KEYS = ("install", "lint", "typecheck", "test", "build")


@dataclass(frozen=True)
class DetectedCommand:
    command: str
    source: str  # "declared" | "inferred"
    confidence: str  # "high" | "medium" | "low"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --- Python ------------------------------------------------------------------


def _detect_python(repo: Path) -> bool:
    return any(
        (repo / name).is_file()
        for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
    )


def _load_pyproject(repo: Path) -> dict:
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    try:
        return tomllib.loads(_read_text(pyproject))
    except tomllib.TOMLDecodeError:
        return {}


def _python_commands(repo: Path) -> dict[str, DetectedCommand]:
    commands: dict[str, DetectedCommand] = {}
    data = _load_pyproject(repo)
    tools = data.get("tool", {}) if isinstance(data, dict) else {}

    installable = any(
        (repo / name).is_file() for name in ("pyproject.toml", "setup.py", "setup.cfg")
    )
    if installable:
        commands["install"] = DetectedCommand("pip install -e .", "inferred", "medium")
    elif (repo / "requirements.txt").is_file():
        commands["install"] = DetectedCommand(
            "pip install -r requirements.txt", "inferred", "medium"
        )

    if (repo / "tox.ini").is_file():
        commands["test"] = DetectedCommand("tox", "declared", "high")
    elif (repo / "noxfile.py").is_file():
        commands["test"] = DetectedCommand("nox", "declared", "high")
    elif "pytest" in tools or (repo / "tests").is_dir():
        commands["test"] = DetectedCommand("pytest", "inferred", "medium")

    if "ruff" in tools or (repo / "ruff.toml").is_file() or (repo / ".ruff.toml").is_file():
        commands["lint"] = DetectedCommand("ruff check .", "inferred", "medium")

    if "mypy" in tools or (repo / "mypy.ini").is_file():
        commands["typecheck"] = DetectedCommand("mypy .", "inferred", "medium")

    if "build-system" in data:
        commands["build"] = DetectedCommand("python -m build", "inferred", "low")

    return commands


# --- Node / TypeScript ---------------------------------------------------------


def _detect_node(repo: Path) -> bool:
    return (repo / "package.json").is_file()


def _node_package_manager(repo: Path) -> str:
    if (repo / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (repo / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _load_package_json(repo: Path) -> dict:
    try:
        data = json.loads(_read_text(repo / "package.json"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _node_commands(repo: Path) -> dict[str, DetectedCommand]:
    commands: dict[str, DetectedCommand] = {}
    pm = _node_package_manager(repo)
    commands["install"] = DetectedCommand(f"{pm} install", "inferred", "medium")

    scripts = _load_package_json(repo).get("scripts", {})
    if not isinstance(scripts, dict):
        scripts = {}

    if "test" in scripts:
        commands["test"] = DetectedCommand(f"{pm} test", "declared", "high")
    if "lint" in scripts:
        commands["lint"] = DetectedCommand(f"{pm} run lint", "declared", "high")
    if "build" in scripts:
        commands["build"] = DetectedCommand(f"{pm} run build", "declared", "high")

    if "typecheck" in scripts:
        commands["typecheck"] = DetectedCommand(f"{pm} run typecheck", "declared", "high")
    elif (repo / "tsconfig.json").is_file():
        commands["typecheck"] = DetectedCommand("tsc --noEmit", "inferred", "medium")

    return commands


# --- Makefile fallback ---------------------------------------------------------

_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:(?!=)")


def _detect_makefile(repo: Path) -> bool:
    return (repo / "Makefile").is_file() or (repo / "makefile").is_file()


def _makefile_path(repo: Path) -> Path:
    return repo / "Makefile" if (repo / "Makefile").is_file() else repo / "makefile"


def _makefile_targets(repo: Path) -> set[str]:
    try:
        text = _read_text(_makefile_path(repo))
    except OSError:
        return set()
    return {
        match.group(1)
        for line in text.splitlines()
        if (match := _MAKE_TARGET_RE.match(line))
    }


def _makefile_commands(repo: Path) -> dict[str, DetectedCommand]:
    targets = _makefile_targets(repo)
    return {
        key: DetectedCommand(f"make {key}", "declared", "high")
        for key in COMMAND_KEYS
        if key in targets
    }


# Extensible registry (issue scope: Python, Node/TypeScript, Makefile fallback).
# Checked in order; the first matching Ecosystem wins.
_ECOSYSTEMS = (
    ("python", _detect_python, _python_commands),
    ("node", _detect_node, _node_commands),
    ("makefile", _detect_makefile, _makefile_commands),
)


def detect_ecosystem(repo: Path) -> tuple[str, dict[str, DetectedCommand]]:
    """Identify the primary Ecosystem and its verification commands. Unknown
    ecosystem (no registered detector matches) returns `("unknown", {})` rather
    than raising."""
    for name, detect, commands_fn in _ECOSYSTEMS:
        if detect(repo):
            return name, commands_fn(repo)
    return "unknown", {}


# --- Repository Instructions ----------------------------------------------------


def _discover_instruction_files(repo: Path) -> list[Path]:
    found: list[Path] = []
    for rel in INSTRUCTION_PATHS:
        path = repo / rel
        if path.is_dir():
            found.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        elif path.is_file():
            found.append(path)
    return found


def _discover_instructions(repo: Path) -> list[dict]:
    instructions = []
    for path in _discover_instruction_files(repo):
        text = _read_text(path)
        size_bytes = len(text.encode("utf-8"))
        truncated = len(text) > MAX_INSTRUCTION_CHARS
        instructions.append(
            {
                "path": path.relative_to(repo).as_posix(),
                "size_bytes": size_bytes,
                "truncated": truncated,
                "content": text[:MAX_INSTRUCTION_CHARS],
            }
        )
    return instructions


# --- Secret files (presence only) -----------------------------------------------


def _discover_secrets(repo: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIR_NAMES)
        rel_dir = Path(dirpath).relative_to(repo)
        for filename in sorted(filenames):
            if any(fnmatch.fnmatch(filename, pattern) for pattern in SECRET_FILENAME_PATTERNS):
                rel_path = filename if str(rel_dir) == "." else (rel_dir / filename).as_posix()
                found.append(rel_path)
    return sorted(found)


# --- Repo Profile ----------------------------------------------------------------


def build_profile(target_repo: Path) -> dict:
    """Build the deterministic Repo Profile for `target_repo` (CONTEXT.md: Repo
    Profile). Same repo -> same result; no model call; never reads the contents of
    a detected secret file."""
    repo = Path(target_repo)
    ecosystem, commands = detect_ecosystem(repo)

    return {
        "target_repo": str(repo),
        "ecosystem": ecosystem,
        "degraded": not commands,
        "commands": {key: asdict(command) for key, command in commands.items()},
        "instructions": _discover_instructions(repo),
        "secrets_detected": _discover_secrets(repo),
        "secret_values_included": False,
    }

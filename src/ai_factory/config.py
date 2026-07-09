"""Layered configuration and the repo-vs-user trust split (ADR-0008,
CONTEXT.md: Repo Config).

Precedence: CLI flags > repo `factory.toml` (target-controlled) > user config
(`${XDG_CONFIG_HOME:-~/.config}/ai-factory/config.toml`, trusted) > built-in
defaults. Repo config may set verification commands (still deny-list-checked
by `verify.py`, recorded with `source: repo_config`/`config_path`) and a Risk
Level override, and may select a Backend **by name only** -- it may never
define a backend command template/preset, because a template chooses which
executable the Factory runs (ADR-0006/0008). Presets are extensible only from
user config or built-ins.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .presets.registry import PRESETS as BUILTIN_PRESETS

REPO_CONFIG_FILENAME = "factory.toml"
USER_CONFIG_RELATIVE_PATH = Path("ai-factory") / "config.toml"


class ConfigError(RuntimeError):
    """Raised for a malformed config file, or when repo config attempts
    something it is not trusted to do (e.g. defining a backend command
    template instead of selecting a Backend by name)."""


@dataclass(frozen=True)
class ResolvedConfig:
    backend_name: str
    backend_source: str  # "cli" | "repo_config" | "user_config" | "default"
    presets: dict[str, str]
    commands: dict[str, dict]  # key -> {"command", "source", "confidence", ["config_path"]}
    risk_override: str | None
    risk_override_source: str | None  # "repo_config" | None
    repo_config_path: Path
    user_config_path: Path


def user_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / USER_CONFIG_RELATIVE_PATH


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"failed to parse '{path}': {exc}") from exc


def _backend_section(data: dict, path: Path, *, allow_template: bool) -> dict:
    backend = data.get("backend")
    if backend is None:
        return {}
    if not isinstance(backend, dict):
        raise ConfigError(f"'{path}': [backend] must be a table")
    if not allow_template:
        disallowed = set(backend) - {"name"}
        if disallowed:
            raise ConfigError(
                f"repo config '{path}' may only select a Backend by name "
                f"([backend] name = \"...\"); it may not define {sorted(disallowed)} "
                "-- backend command templates/presets come only from user "
                "config or built-ins (ADR-0006/0008)"
            )
    return backend


def _commands_section(data: dict, path: Path) -> dict[str, str]:
    commands = data.get("commands")
    if commands is None:
        return {}
    if not isinstance(commands, dict):
        raise ConfigError(f"'{path}': [commands] must be a table")
    for key, value in commands.items():
        if not isinstance(value, str):
            raise ConfigError(f"'{path}': [commands].{key} must be a string command")
    return dict(commands)


def _user_presets(data: dict, path: Path) -> dict[str, str]:
    presets = data.get("presets")
    if presets is None:
        return {}
    if not isinstance(presets, dict):
        raise ConfigError(f"'{path}': [presets] must be a table")
    for name, template in presets.items():
        if not isinstance(template, str):
            raise ConfigError(f"'{path}': [presets].{name} must be a string command template")
    return dict(presets)


def load_config(target_repo: Path, cli_backend: str | None = None) -> ResolvedConfig:
    """Resolve the layered config for a Run against `target_repo`. Reads the
    repo's `factory.toml` (target-controlled, never trusted with backend
    templates) and the user's `config.toml` (trusted), then applies the
    precedence CLI > repo > user > default independently for the backend name
    and for verification commands."""
    user_path = user_config_path()
    user_data = _load_toml(user_path)
    user_backend = _backend_section(user_data, user_path, allow_template=True)
    user_presets = _user_presets(user_data, user_path)
    user_commands = _commands_section(user_data, user_path)

    repo_path = Path(target_repo) / REPO_CONFIG_FILENAME
    repo_data = _load_toml(repo_path)
    repo_backend = _backend_section(repo_data, repo_path, allow_template=False)
    repo_commands = _commands_section(repo_data, repo_path)
    repo_risk = repo_data.get("risk")
    repo_risk_override = None
    if isinstance(repo_risk, dict):
        repo_risk_override = repo_risk.get("override")

    presets = dict(BUILTIN_PRESETS)
    presets.update(user_presets)

    if cli_backend is not None:
        backend_name, backend_source = cli_backend, "cli"
    elif repo_backend.get("name") is not None:
        backend_name, backend_source = repo_backend["name"], "repo_config"
    elif user_backend.get("name") is not None:
        backend_name, backend_source = user_backend["name"], "user_config"
    else:
        backend_name, backend_source = "manual", "default"

    commands: dict[str, dict] = {}
    for key, command in user_commands.items():
        commands[key] = {"command": command, "source": "user_config", "confidence": "high"}
    for key, command in repo_commands.items():
        commands[key] = {
            "command": command,
            "source": "repo_config",
            "confidence": "high",
            "config_path": str(repo_path),
        }

    if repo_risk_override is not None:
        risk_override, risk_override_source = repo_risk_override, "repo_config"
    else:
        risk_override, risk_override_source = None, None

    return ResolvedConfig(
        backend_name=backend_name,
        backend_source=backend_source,
        presets=presets,
        commands=commands,
        risk_override=risk_override,
        risk_override_source=risk_override_source,
        repo_config_path=repo_path,
        user_config_path=user_path,
    )


def merge_profile_commands(profile: dict, resolved: ResolvedConfig) -> dict:
    """Layer `resolved.commands` (repo config over user config) on top of the
    Repo Profile's detected commands, and recompute `degraded` accordingly.
    Returns a new profile dict; does not mutate `profile`."""
    merged_commands = dict(profile.get("commands", {}))
    merged_commands.update(resolved.commands)
    return {**profile, "commands": merged_commands, "degraded": not merged_commands}

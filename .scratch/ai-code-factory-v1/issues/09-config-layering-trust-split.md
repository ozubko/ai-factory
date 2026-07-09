# Config layering + trust split + backend selection

Status: done

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

Layered configuration with precedence: CLI flags > repo `factory.toml` > user config
(`$XDG_CONFIG_HOME/ai-factory/config.toml`) > built-in defaults. Repo config may set
verification commands (recorded `source: repo_config`, still deny-list-checked),
ecosystem hints, preferences, and a risk override, and may select a Backend **by name
only** — it may NOT define backend command templates/presets (those come only from
user config or built-ins, because a template chooses which executable the Factory
runs). `--backend <name>` selects the Backend; `--state-dir` / `AI_FACTORY_STATE_DIR`
redirects the State Dir. Codex/Claude ship as documented user-config/built-in Presets
over the Subprocess backend. See ADR-0006, 0008.

## Acceptance criteria

- [ ] Precedence resolves CLI > repo > user > default for commands and backend name
- [ ] A repo-config command is recorded with `source: repo_config` and is deny-list-checked
- [ ] Repo config attempting to define a command template is ignored/rejected (name-only backend select)
- [ ] `--state-dir` / `AI_FACTORY_STATE_DIR` redirects all run artifacts
- [ ] `--backend` selects the backend/preset

## Blocked by

- Issue 04 (`issues/04-verification-gate-fix-loop.md`)

## Comments

Implemented in `src/ai_factory/config.py` (`load_config`, `ResolvedConfig`,
`merge_profile_commands`, `ConfigError`) and wired into `runner.py` via a
`_load_config` helper used by `run_manual`, `plan_task`, `implement_task`,
`review_task`, and `run_task`:

- Backend name precedence: `--backend` CLI flag > repo `factory.toml`
  `[backend] name` > user `config.toml` `[backend] name` > built-in default
  (`"manual"`). `cli.py`'s `--backend` now defaults to `None` on `run` so the
  layers below CLI get a chance to apply; `plan` still requires an explicit
  `--backend` (staged driving needs a worktree-creating backend).
- Repo config `[backend]` may only contain `name` -- any other key (e.g. an
  attempted `command`/template override) raises `ConfigError`, surfaced to the
  CLI as a `RunError` refusing the Run, per ADR-0006/0008's trust split.
  Presets (command templates) are extensible only via user `config.toml`
  `[presets]` or the built-in registry; `SubprocessBackend` templates are
  resolved from `ResolvedConfig.presets` everywhere `PRESETS` used to be used
  directly.
- Verification commands: repo `factory.toml` `[commands]` > user
  `config.toml` `[commands]` > the Repo Profile's detected commands.
  `config.merge_profile_commands` layers `ResolvedConfig.commands` over the
  profile's detected commands; repo-sourced entries are recorded with
  `source: "repo_config"` and `config_path` (the absolute path to the repo's
  `factory.toml`), user-sourced entries with `source: "user_config"`. Every
  merged command still flows through the existing Verification Gate
  (`verify.py`), which deny-list-checks every command before any of them run
  -- a repo config command matching the Command Deny-list refuses the whole
  Run exactly as a detected one would.
- A repo `factory.toml` `[risk]` `override` key is parsed as a lower-precedence
  default for `--risk` (CLI still wins if passed).
- `--state-dir` / `AI_FACTORY_STATE_DIR` already redirected all run artifacts
  before this issue (`state_dir.py`); verified still correct end-to-end here.

Test coverage: new `tests/test_config_layering_trust_split.py` (backend
precedence unit test across all four layers, command precedence unit test,
a repo-config backend-template rejection unit test, and two end-to-end `run`
tests -- one showing a repo-config command recorded with `source:
repo_config` and passing verification, one showing a deny-listed repo-config
command refuses the Run -- plus a State Dir env-var redirection check).
Updated `tests/test_manual_mode_staged_commands.py::test_manual_backend_cannot_drive_staged_phases`:
since `--backend` is no longer a fixed argparse `choices` list (presets are
now dynamic, extensible via user config), `plan --backend manual` is rejected
at runtime (`RunError`, exit 1) rather than at argparse parse time (exit 2);
the test now asserts the new, still-correct behavior. Full suite: 112 passed;
`ruff check` and `mypy` clean on all touched files.

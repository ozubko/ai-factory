# Config layering + trust split + backend selection

Status: ready-for-agent

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

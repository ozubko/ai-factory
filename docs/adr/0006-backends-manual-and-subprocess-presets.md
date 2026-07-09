# Backends: Manual + one generic SubprocessBackend; vendors are config presets

v1 ships exactly two `AgentBackend` implementations — `ManualBackend` (default, no
model) and a generic `SubprocessBackend` that runs a configurable command
template. Codex, Claude, and the test `fake` are named **presets** (data in
`factory.toml`), not bespoke Python classes. The factory is an agent-agnostic
delivery harness, not a Codex or Claude wrapper; keeping vendors as presets keeps
CLI churn outside the stable core.

**Prompt/artifact contract.** Prompts are written as files to the run's
`bundles/` dir (`<phase>-system.md`, `<phase>-user.md`, `<phase>-combined.md`); a
`combined` file always exists because some CLIs don't separate system/user. The
backend captures stdout/stderr to phase logs and guarantees the phase's
`output_path` artifact exists (the CLI writes it, or the backend writes captured
stdout). For `implement`, the source of truth remains the git-observed worktree;
the `output_path` is only a summary/log.

**Selection precedence:** `--backend <name>` > `factory.toml [backend].name` >
`manual`.

**v1 validation:** ManualBackend and SubprocessBackend are validated end-to-end
against a fake agent CLI (covering: prompt-file passing, subprocess in worktree,
stdout/stderr capture, output_path enforcement, repo-mutation detection, git-diff
collection, verification, phase-level resume, and contract-violation detection).
Real Codex/Claude presets are documented and usable but **not CI-gated** — they
depend on the user's installed, authenticated CLI and are overridable in config.

## Considered Options

- **Generic SubprocessBackend + presets** (chosen).
- **Bespoke CodexBackend/ClaudeBackend** — rejected for v1: brittle against CLI
  flag churn and re-couples the core to specific vendors. Revisit only with
  repeated evidence that presets are insufficient.

## Note

v1 uses shell command templates with `{placeholders}`. A future argv-based preset
format (`argv = [...]` + `stdin_file`) is planned to avoid shell-quoting issues.

**Addendum (adding real `codex`/`claude` presets):** `SubprocessBackend` pipes
`combined_prompt_path`'s contents to the child process's stdin unconditionally —
required for CLIs (confirmed: Codex) that read their prompt from stdin rather than
a positional argument, and harmless for CLIs that ignore stdin. A `run_dir`
placeholder (`output_path`'s parent — where `bundles/` and phase outputs live,
outside the worktree) was added so a preset's own directory sandboxing (e.g.
`--add-dir`) can be granted access to them. Neither addition changes the "plain
argv, no shell" execution model.

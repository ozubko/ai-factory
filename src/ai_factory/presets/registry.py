"""Named Backend Presets (ADR-0006). Vendors are data, not code.

Presets may be either legacy command-template strings or structured mappings. The
preferred structured form is `{"argv": [...]}`: each argv token is rendered
independently with placeholders, so paths containing spaces are not split apart.
Available placeholders: python, phase, mode, sandbox_mode, workdir,
system_prompt_path, user_prompt_path, combined_prompt_path, output_path, run_dir
(the parent directory of output_path — also where bundles/ lives, outside the
worktree). `sandbox_mode` is phase-aware: read-only phases render `read-only`,
while read-write phases render `workspace-write`.

Repo config may only select a preset by name — it can never define a template
(ADR-0007/0008); this registry is the sole source of built-in templates in v1.
User config (`[presets]` in config.toml) may add or override entries.

The `codex`/`claude` templates below are written against each CLI's documented
flags but, per ADR-0006, are **not exercised against a live model call in CI** —
only `fake`/`manual` are. Treat them as a verified starting point, not a
guarantee: if your installed CLI version differs, override the entry in your
own `~/.config/ai-factory/config.toml` `[presets]` table rather than editing
this file.
"""

from __future__ import annotations

from typing import Any

PresetSpec = str | dict[str, Any]

PRESETS: dict[str, PresetSpec] = {
    "fake": {
        "argv": [
            "{python}",
            "-m",
            "ai_factory.presets.fake_agent",
            "--phase",
            "{phase}",
            "--output",
            "{output_path}",
        ]
    },
    # OpenAI Codex CLI. `codex exec` reads a piped stdin prompt directly (no
    # positional prompt argument needed) and prints only the final agent
    # message to stdout, which SubprocessBackend captures as output_path if
    # `codex` doesn't write it itself. `{sandbox_mode}` makes plan/review run
    # with a read-only CLI sandbox while implement/fix get workspace-write.
    # The Factory still enforces read-only Phases with git afterwards
    # (ADR-0004); the CLI sandbox is defense-in-depth.
    "codex": {
        "argv": [
            "codex",
            "exec",
            "--cd",
            "{workdir}",
            "--sandbox",
            "{sandbox_mode}",
        ]
    },
    # Anthropic Claude Code, headless mode. `claude -p` takes its prompt only
    # as a positional argument (no prompt-file flag, and stdin support for the
    # prompt itself isn't documented) — so we point it at the combined prompt
    # file and let Claude Code's own Read tool open it. `--add-dir` grants
    # access to `workdir` and `run_dir` without relying on fragile shell
    # quoting; every path is passed as its own argv token.
    "claude": {
        "argv": [
            "claude",
            "-p",
            (
                "Read the file at {combined_prompt_path} and follow its instructions "
                "exactly. If it asks you to produce a file at a specific path, write "
                "it there; otherwise print the requested result as your final response."
            ),
            "--add-dir",
            "{workdir}",
            "--add-dir",
            "{run_dir}",
            "--permission-mode",
            "acceptEdits",
        ]
    },
    # Test-only preset: makes the Fake Agent misbehave during read-only Phases
    # (plan/review), so the Factory's Contract Violation detection can be
    # exercised end-to-end (CONTEXT.md: Contract Violation).
    "fake-readonly-violator": {
        "argv": [
            "{python}",
            "-m",
            "ai_factory.presets.fake_agent",
            "--phase",
            "{phase}",
            "--output",
            "{output_path}",
            "--mutate-readonly",
        ]
    },
    # Test-only preset: like `fake-readonly-violator`, but scoped to the
    # `review` Phase only, so the Diff Review Contract Violation path can be
    # exercised without the `plan` Phase halting the Run first.
    "fake-review-violator": {
        "argv": [
            "{python}",
            "-m",
            "ai_factory.presets.fake_agent",
            "--phase",
            "{phase}",
            "--output",
            "{output_path}",
            "--mutate-readonly",
            "--mutate-readonly-phase",
            "review",
        ]
    },
}

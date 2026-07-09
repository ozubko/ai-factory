"""Named Backend Presets (ADR-0006). Vendors are data, not code.

Command templates use `{placeholder}` tokens rendered by `SubprocessBackend`.
Available placeholders: python, phase, workdir, system_prompt_path,
user_prompt_path, combined_prompt_path, output_path, run_dir (the parent
directory of output_path — also where bundles/ lives, outside the worktree).
`SubprocessBackend` runs the template as plain argv (no shell), and pipes
combined_prompt_path's contents to the process's stdin.

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

PRESETS: dict[str, str] = {
    "fake": (
        "{python} -m ai_factory.presets.fake_agent "
        "--phase {phase} --output {output_path}"
    ),
    # OpenAI Codex CLI. `codex exec` reads a piped stdin prompt directly (no
    # positional prompt argument needed) and prints only the final agent
    # message to stdout, which SubprocessBackend captures as output_path if
    # `codex` doesn't write it itself. `--sandbox workspace-write` lets it edit
    # files under `workdir`; the Factory's own read-only enforcement (not this
    # flag) is what actually catches a plan/review Phase that mutates the
    # worktree (ADR-0004). Adjust `--sandbox` (e.g. to `read-only`) if your
    # policy wants the CLI to also self-restrict.
    "codex": "codex exec --cd {workdir} --sandbox workspace-write",
    # Anthropic Claude Code, headless mode. `claude -p` takes its prompt only
    # as a positional argument (no prompt-file flag, and stdin support for the
    # prompt itself isn't documented) — so instead of inlining the whole
    # prompt as an argv string (a shell-quoting hazard `SubprocessBackend`
    # deliberately avoids), we point it at the combined prompt file and let
    # Claude Code's own Read tool open it. `--add-dir` grants access to
    # `workdir` (to edit the worktree) and `run_dir` (to read the prompt
    # bundle and, optionally, write output_path itself). `--permission-mode
    # acceptEdits` auto-accepts file edits but still gates shell commands
    # behind approval — fine for `plan`/`review`, but an `implement`/`fix`
    # Phase that needs to run shell commands unattended will stall on that
    # approval prompt with no human present. For a fully unattended run,
    # override this preset with `--dangerously-skip-permissions` instead —
    # understand that trade-off before doing so (ADR-0007: agent execution
    # safety is delegated to the backend/preset, not the Factory).
    "claude": (
        "claude -p "
        '"Read the file at {combined_prompt_path} and follow its instructions '
        'exactly. If it asks you to produce a file at a specific path, write it '
        'there; otherwise print the requested result as your final response." '
        "--add-dir {workdir} --add-dir {run_dir} --permission-mode acceptEdits"
    ),
    # Test-only preset: makes the Fake Agent misbehave during read-only Phases
    # (plan/review), so the Factory's Contract Violation detection can be
    # exercised end-to-end (CONTEXT.md: Contract Violation).
    "fake-readonly-violator": (
        "{python} -m ai_factory.presets.fake_agent "
        "--phase {phase} --output {output_path} --mutate-readonly"
    ),
    # Test-only preset: like `fake-readonly-violator`, but scoped to the
    # `review` Phase only, so the Diff Review Contract Violation path can be
    # exercised without the `plan` Phase halting the Run first.
    "fake-review-violator": (
        "{python} -m ai_factory.presets.fake_agent "
        "--phase {phase} --output {output_path} "
        "--mutate-readonly --mutate-readonly-phase review"
    ),
}

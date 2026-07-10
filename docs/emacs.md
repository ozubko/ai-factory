# Emacs cockpit

`ai-factory.el` is a small Emacs frontend for the `ai-factory` CLI.

It is deliberately a **cockpit**, not a second implementation of the Factory:

- the CLI still owns repo profiling, risk classification, worktree isolation, backend invocation, verification, reports, and cleanup;
- Emacs only starts CLI commands, reads `metadata.json`, and opens run artifacts in buffers.

## Install locally

From the repository root, add the `emacs/` directory to your Emacs load path:

```elisp
(add-to-list 'load-path "/path/to/ai-factory/emacs")
(require 'ai-factory)
```

Make sure the `ai-factory` command is available on your shell `PATH`:

```bash
pip install -e ".[dev]"
ai-factory --help
```

If your Emacs cannot see the same `PATH` as your terminal, customize:

```elisp
(setq ai-factory-command "/absolute/path/to/ai-factory")
```

## Start with the run list

Run:

```text
M-x ai-factory-list
```

This opens `*AI Factory Runs*`, a table of known runs from the Factory State Dir.

The default State Dir follows the CLI convention:

```text
AI_FACTORY_STATE_DIR
$XDG_STATE_HOME/ai-factory
~/.local/state/ai-factory
```

You can override it in Emacs:

```elisp
(setq ai-factory-state-dir "/custom/state/ai-factory")
```

## Run list keys

Inside `*AI Factory Runs*`:

| Key | Action |
| --- | --- |
| `RET` | Open run detail buffer |
| `g` | Refresh run list |
| `r` | Start `ai-factory run` |
| `p` | Start `ai-factory plan` |
| `i` | Continue selected run with `implement` |
| `v` | Run review for selected run |
| `P` | Open `plan.md` |
| `R` | Open `report.md` |
| `D` | Open `diff.patch` |
| `m` | Open worktree in Magit, or Dired if Magit is unavailable |
| `c` | Clean selected run after confirmation |

## Common workflow

### 1. Create a safe fake run

```text
M-x ai-factory-run
```

Choose:

```text
Target repo: /path/to/clean/git/repo
Task: demo task
Backend: fake
```

The command runs asynchronously in a compilation buffer, so long-running agent output stays visible.

Then refresh the list:

```text
M-x ai-factory-list
```

or press `g` in the run list.

### 2. Inspect the run

In `*AI Factory Runs*`, press `RET` on a run.

The detail buffer gives quick actions:

- open `plan.md`;
- open `report.md`;
- open `diff.patch`;
- open `pr-body.md`;
- open the run worktree in Dired;
- open the run worktree in Magit;
- continue with implement/review/resume;
- clean the run.

### 3. Use Magit for the diff

If Magit is installed, press `m` on a run.

This opens `magit-status` in the Factory worktree:

```text
~/.local/state/ai-factory/runs/<run-id>/worktree
```

That lets you inspect the generated branch and diff using your normal Git workflow.

## Useful commands

```text
M-x ai-factory-run
M-x ai-factory-plan
M-x ai-factory-list
M-x ai-factory-open-run
M-x ai-factory-open-plan
M-x ai-factory-open-report
M-x ai-factory-open-diff
M-x ai-factory-open-pr-body
M-x ai-factory-open-worktree
M-x ai-factory-magit-worktree
M-x ai-factory-implement
M-x ai-factory-review
M-x ai-factory-resume
M-x ai-factory-clean
```

## Design boundary

The Emacs package should stay thin.

It should not:

- create git worktrees itself;
- classify risk;
- run agents directly;
- parse source code;
- decide whether a run may continue;
- replace the CLI's verification gate;
- push, merge, or open PRs.

Those responsibilities belong to `ai-factory` itself.

The Emacs package exists to make the CLI easier to drive and review from the editor.

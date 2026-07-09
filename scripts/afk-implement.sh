#!/usr/bin/env bash
#
# afk-implement.sh — run the AI Code Factory v1 issues AFK (away from keyboard)
# via headless Claude Code, one fresh session per issue, in dependency order.
#
# Each issue is implemented in its own `claude -p` run (a fresh context, which is
# exactly the "one fresh session per issue" hygiene the flow wants). The handoff
# doc and PRD are wired into every session's context.
#
# Usage:
#   bash scripts/afk-implement.sh                 # run all issues, in order
#   bash scripts/afk-implement.sh 03-... 04-...   # run only the named issues
#
# Override any of the config below via environment variables, e.g.:
#   COMMIT=1 CLAUDE_FLAGS="--dangerously-skip-permissions" bash scripts/afk-implement.sh
#
set -euo pipefail

# ---- Config (override via env) ---------------------------------------------
REPO="${REPO:-/Users/oleksandr.zubko/Projects/ai-factory}"
FEATURE_DIR="${FEATURE_DIR:-$REPO/.scratch/ai-code-factory-v1}"
ISSUES_DIR="${ISSUES_DIR:-$FEATURE_DIR/issues}"
PRD="${PRD:-$FEATURE_DIR/PRD.md}"

HANDOFF="${HANDOFF:-$REPO/.scratch/handoff-ai-code-factory-v1.md}"

LOG_DIR="${LOG_DIR:-$FEATURE_DIR/afk-logs}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

# Model + reasoning effort for each headless session. Pinned explicitly so runs do
# NOT inherit your interactive default (which is Opus 4.8 / xhigh in this setup).
# --model takes an alias ('sonnet','opus','fable') or a full id ('claude-sonnet-5');
# --effort is one of low|medium|high|xhigh|max.
MODEL="${MODEL:-sonnet}"
EFFORT="${EFFORT:-medium}"

# Headless permission posture. `acceptEdits` auto-accepts file edits but may still
# prompt for shell commands. For a fully unattended run you likely want:
#   CLAUDE_FLAGS="--dangerously-skip-permissions"   (understand the risk first)
CLAUDE_FLAGS="${CLAUDE_FLAGS:---permission-mode acceptEdits}"

# Commit a checkpoint after each successful issue. OFF by default: issue 01 is
# responsible for creating .gitignore (so .venv/.idea aren't swept in) — only turn
# this on once you trust that, or the first `git add -A` will stage junk.
COMMIT="${COMMIT:-0}"

# Abort the whole run if an issue fails. ON by default: later issues depend on
# earlier ones landing correctly.
STOP_ON_FAIL="${STOP_ON_FAIL:-1}"

# Dependency-topological order. The numeric prefixes already respect every
# "Blocked by" relationship, so left-to-right is a valid build order.
DEFAULT_ISSUES=(
  01-walking-skeleton
  02-isolation-preconditions-cleanup
  03-profiling-command-detection
  04-verification-gate-fix-loop
  05-planning-phase-prompts
  06-risk-aware-lifecycle
  07-reporting-pr-body-review
  08-manual-mode-staged-commands
  09-config-layering-trust-split
  10-resume-partial-change-safety
)

# ---- Preflight -------------------------------------------------------------
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || { echo "ERROR: '$CLAUDE_BIN' not found on PATH." >&2; exit 127; }
[ -d "$REPO" ]        || { echo "ERROR: repo not found: $REPO" >&2; exit 1; }
[ -f "$PRD" ]         || { echo "ERROR: PRD not found: $PRD" >&2; exit 1; }
[ -f "$HANDOFF" ]     || echo "WARN: handoff not found (it lives in a session-temp dir): $HANDOFF" >&2
mkdir -p "$LOG_DIR"
cd "$REPO"

# Grant the headless agent read access to the handoff's directory (it lives
# outside the repo, which Claude Code otherwise won't read).
read -r -a FLAGS <<< "$CLAUDE_FLAGS"
FLAGS+=(--model "$MODEL" --effort "$EFFORT" --add-dir "$(dirname "$HANDOFF")")

if [ "$#" -gt 0 ]; then ISSUES=("$@"); else ISSUES=("${DEFAULT_ISSUES[@]}"); fi

echo "AFK build: ${#ISSUES[@]} issue(s), sequential, in $REPO"
echo "Model: $MODEL   Effort: $EFFORT"
echo "Reminder: YOU are the merge gate — review each slice's diff before relying on it."
echo

# ---- Run -------------------------------------------------------------------
for name in "${ISSUES[@]}"; do
  name="${name%.md}"                       # tolerate a trailing .md
  issue="$ISSUES_DIR/$name.md"
  log="$LOG_DIR/$name.log"
  if [ ! -f "$issue" ]; then echo "SKIP: missing issue $issue" >&2; continue; fi

  echo "=== Implementing $name ==="
  prompt="You are implementing ONE issue of the AI Code Factory v1, AFK (no human present).

Read these for context first (use the Read tool):
- Handoff: $HANDOFF
- PRD: $PRD
- This issue: $issue
- Also honor $REPO/CONTEXT.md (domain glossary) and $REPO/docs/adr/ (decisions).

Task: implement EXACTLY this issue, end-to-end. Use the /implement skill if it is
available; otherwise follow a test-first, vertical-slice workflow to satisfy the
issue's acceptance criteria.

Rules:
- Only this issue. Do NOT start blocked or other issues.
- Use CONTEXT.md vocabulary and respect the ADRs. Zero runtime dependencies (stdlib only).
- Do NOT push, merge, or open PRs. Do NOT modify files outside $REPO.
- Preserve the safety invariants (never touch a target's working tree; deny-list refuses;
  secret values never enter artifacts; verification/risk are deterministic and factory-owned).
- When done, update this issue's 'Status:' line to reflect completion and append a short
  summary under a '## Comments' heading in $issue.
Then stop."

  if "$CLAUDE_BIN" "${FLAGS[@]}" -p "$prompt" 2>&1 | tee "$log"; then
    echo "OK: $name  (log: $log)"
    if [ "$COMMIT" = "1" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git add -A && git commit -m "AFK: implement $name" >/dev/null 2>&1 && echo "  checkpoint committed" || echo "  (nothing to commit)"
    fi
  else
    echo "FAIL: $name  (see $log)" >&2
    if [ "$STOP_ON_FAIL" = "1" ]; then echo "Stopping (STOP_ON_FAIL=1)." >&2; exit 1; fi
  fi
  echo
done

echo "AFK build finished. Review the diffs and the .scratch issue statuses before merging."

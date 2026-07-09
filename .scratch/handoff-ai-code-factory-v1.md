# Handoff — AI Code Factory v1

## Purpose of the next session

Implement **AI Code Factory v1** — a local, repo-portable *agentic engineering
harness* (risk-aware, git-isolated, never lands code). Design and planning are
complete; the next sessions build it, **one issue per fresh session**, in dependency
order, via `/implement`.

## Current state

- No code written yet — the repo is still empty of `src/` (only design artifacts, a
  `.venv`, and `.idea/`).
- The repo is **not git-initialised**. The very first implementation task (issue 01)
  includes `git init` + an initial commit — required before the Factory can be
  dogfooded in Automation Mode (clean-git precondition).
- Design was hardened via a grilling session; every hard-to-reverse decision is an
  ADR. A risk-aware lifecycle was added late (ADR-0014, amends ADR-0003).

## Where everything lives (read these; don't re-derive)

Workspace root: `/Users/oleksandr.zubko/Projects/ai-factory/`

- **Glossary:** `CONTEXT.md` — use this vocabulary in code/tests/issues (terms have
  `_Avoid_` synonyms).
- **Decisions:** `docs/adr/0001–0014` — read the ADRs for the area you touch. 0014 is
  the risk-aware lifecycle and amends 0003.
- **PRD:** `.scratch/ai-code-factory-v1/PRD.md` (`Status: ready-for-agent`) — problem,
  solution, 61 user stories, implementation + testing decisions, out-of-scope.
- **Issues (tracer-bullet slices):** `.scratch/ai-code-factory-v1/issues/01…10-*.md`,
  each `Status: ready-for-agent` with What-to-build / Acceptance criteria / Blocked-by.
- **Full implementation plan:** `/Users/oleksandr.zubko/.claude/plans/portable-ai-code-streamed-dongarra.md`
  (module layout, lifecycle, state-dir layout, verification commands, acceptance).
- **Agent config:** `AGENTS.md` + `docs/agents/{issue-tracker,triage-labels,domain}.md`
  — local-markdown tracker (no GitHub); issues/PRDs live under `.scratch/<feature>/`.

## Dependency order (build in this sequence)

Critical path: **01 → 03 → 05 → 06 → 07**. Branches: 02 (after 01), 04 (after 01,03),
08 (after 05), 09 (after 04), 10 (after 06).

Start with **`issues/01-walking-skeleton.md`** (the only unblocked issue and the
foundation: package scaffold, CLI, AgentBackend seam, Fake Agent, git isolation,
minimal end-to-end `run`).

## Watch-outs / open questions

- **`--auto` semantics (open):** currently specified as the *explicit form of the
  default* classifier-gated policy (proceed only when the classifier permits; does
  NOT override medium/high — that's `--force-implement`). If the intended default is
  instead *conservative* (always pause unless `--auto`), that's a one-line Decision
  Gate flip — confirm with the user when implementing issue 06.
- **Determinism is load-bearing:** the risk classifier and verification command
  detection must be deterministic and factory-owned — never model-decided (ADR-0005,
  0014). Verification is the authoritative gate; agent claims are advisory only.
- **Safety invariants that must never regress:** never touch the target working tree;
  no push/merge/PR; Command Deny-list refuses (not warns); secret *values* never enter
  profiles/bundles/reports; cleanup is scoped to factory-owned resources only.
- **Zero runtime dependencies** (stdlib only); dev-only pytest/ruff/mypy. `git` is a
  hard dependency.
- **Testing:** one code seam (`AgentBackend` + Fake Agent), drive end-to-end through
  the CLI against **real temp git repos**, assert on observable artifacts
  (`metadata.json`, `plan.md`, `report.md`, `diff.patch`, `verify/*.log`, git state);
  plus direct tests of the pure functions (risk, safety, command detection).

## Suggested skills for the next session(s)

- **`/implement`** — pass it the PRD path + a single issue file (start with issue 01).
- **`/tdd`** — build test-first; real git in `tmp_path`, Fake Agent as the double.
- **`/run`** or **`/verify`** — drive `ai-factory` end-to-end to confirm a slice works.
- **`/code-review`** — after each slice lands.
- **`/grill-with-docs`** + **`/domain-modeling`** — only if a *new* design question
  arises mid-build (updates `CONTEXT.md` / ADRs).

## Context hygiene

Start a **fresh session per issue** (issues are independent). Do not carry this design
thread into implementation beyond referencing these artifacts.

## Sensitive information

None in this thread (no keys, secrets, or PII).

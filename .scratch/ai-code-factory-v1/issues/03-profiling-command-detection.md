# Profiling + deterministic command detection + secret redaction

Status: done — verified (all acceptance criteria met; see Comments)

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

`ai-factory profile <target>` plus a `profile` Phase that produces `profile.json`:
primary language/ecosystem via an extensible registry (Python, Node/TypeScript, and a
Makefile fallback in v1); verification commands each tagged with a `source`
(`declared` | `inferred`) and a `confidence`; discovered Repository Instructions
(AGENTS.md, CLAUDE.md, `.cursor/rules`, `.github/copilot-instructions.md`,
CONTRIBUTING.md, README.md) labeled by path and size-capped (truncation recorded);
and detected secret files recorded as presence only (`secrets_detected`,
`secret_values_included: false`). Secret values must never appear in `profile.json`,
any Prompt Bundle, or any report. Command detection is deterministic (the config
override layer lands in issue 09). See ADR-0005, 0007, 0010.

## Acceptance criteria

- [ ] `ai-factory profile .` identifies the ecosystem for Python, Node/TS, and Makefile fixtures
- [ ] Each detected command carries `source` + `confidence`
- [ ] Instruction files are discovered, labeled by path, and truncation recorded
- [ ] `.env`/credential files are recorded as presence only; no secret value appears anywhere
- [ ] Unknown ecosystem → empty commands + degraded flag, no crash
- [ ] Detection is deterministic (same repo → same result) and involves no model call

## Blocked by

- Issue 01 (`issues/01-walking-skeleton.md`)

## Comments

Implemented `src/ai_factory/profiling.py` (stdlib-only: `tomllib`, `json`, `os`,
`re`, `fnmatch`, `dataclasses`) plus `ai-factory profile <target>` wired into
`cli.py`, printing `profile.json` to stdout.

- **Ecosystem registry** (`_ECOSYSTEMS`, checked in order): Python
  (`pyproject.toml`/`setup.py`/`setup.cfg`/`requirements.txt`), Node/TypeScript
  (`package.json`, package manager inferred from lockfile: pnpm/yarn/npm),
  Makefile fallback (`Makefile`/`makefile`, target names parsed with a regex, no
  `make` subprocess invoked at detection time). No detector match → `ecosystem:
  "unknown"`, `commands: {}`, `degraded: true`, no crash.
- **Commands**: keys `install`/`lint`/`typecheck`/`test`/`build`, each tagged
  `source` (`declared` from repo-declared scripts/targets/tox/nox, `inferred` from
  ecosystem heuristics) and `confidence` (`high`/`medium`/`low`). `degraded` is
  `true` whenever zero commands were detected (covers the unknown-ecosystem case
  and any known ecosystem with no usable signal).
- **Repository Instructions**: discovers `AGENTS.md`, `CLAUDE.md`,
  `.cursor/rules` (file or directory), `.github/copilot-instructions.md`,
  `CONTRIBUTING.md`, `README.md`; each entry is labeled by repo-relative path,
  records `size_bytes` and a `truncated` flag, and caps embedded `content` at
  `MAX_INSTRUCTION_CHARS` (4000 chars).
- **Secrets**: presence-only detection (`.env`/`.env.*`, `*.pem`, `*.key`,
  `id_rsa`/`id_dsa`, `credentials.json`, `.npmrc`, `.pypirc`, `secrets.{yaml,yml,json}`)
  via filename matching in an `os.walk` that skips `node_modules`/`.venv`/`.git`/etc.
  — file *contents* are never opened for this check, so secret values cannot reach
  `profile.json`. `secret_values_included` is always `false`.
- Deterministic by construction: no model call, no wall-clock/randomness, sorted
  directory walks and glob results, fixed ecosystem/command-key ordering.

Tests added in `tests/test_profiling.py` covering every acceptance criterion:
Python/Node/Makefile detection with declared-vs-inferred sourcing, unknown-ecosystem
degraded mode, instruction discovery + truncation, secret presence-only recording
(asserting the literal secret value never appears in the serialized profile),
ignored-directory skipping, same-repo-same-result determinism, and the `profile`
CLI command (success + non-directory target refusal).

**Update (follow-up session): verified.** The prior session's sandbox
constraint is gone (`python3`/`pytest` run without an approval block). Ran the
previously-blocked commands directly:

- `python3 -m pytest tests/test_profiling.py -v` → **11 passed**, one per
  acceptance criterion (Python declared+inferred commands, tox precedence over
  inferred pytest, Node declared scripts, Makefile fallback, unknown-ecosystem
  degraded/no-crash, instruction discovery + truncation, secret presence-only
  recording, ignored-directory skipping, same-repo determinism, and the
  `profile` CLI success/refusal paths).
- `python3 -m pytest tests/ -v` → **63 passed** (full suite, no regressions).
- `python3 -m ruff check src/ tests/` → all checks passed.
- `python3 -m mypy src/` → 2 pre-existing errors in `runner.py` (risk/decision
  gate dict typing), unrelated to this issue's scope — same errors already
  flagged and left out-of-scope during issue 02's verification.
- Live smoke test: ran `ai-factory profile .` against this repo itself.
  Output showed `ecosystem: "python"`, `degraded: false`, `install`/`test`/
  `build` commands each tagged `source: "inferred"` + a `confidence`,
  `AGENTS.md` discovered and labeled by path with `truncated: false`, and
  `secrets_detected: []` / `secret_values_included: false` — no secret file
  exists in this repo, and the code path that would record one never opens
  file contents, so no value could leak either way.

All six acceptance criteria are satisfied by the existing implementation (no
code changes were needed this session — the prior session's hand-traced
implementation was correct and is now confirmed by a real test run and a live
CLI smoke test). Status moved to done.

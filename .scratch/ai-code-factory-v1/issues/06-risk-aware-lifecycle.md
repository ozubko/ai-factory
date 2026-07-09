# Risk-aware lifecycle — deterministic classifier + Decision Gate + flags

Status: done — verified (all acceptance criteria met; see Comments)

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

The core feature. A deterministic, factory-owned `risk_classify` Phase (after
profiling) computing a Risk Level (`low` | `medium` | `high`) + `reasons[]` from
task-text keywords, Repo Profile, plan-predicted changed files (available at the
Decision Gate), verification availability, presence/absence of tests, and risky
file/path patterns (auth/authz, security/secrets, DB migrations, data
mutation/deletion, infra/CI-CD/Terraform/K8s, payments, public API, broad refactor).
**No model call.** A Decision Gate after `plan`: by default automation continues to
`implement` only when the level is `low`; `medium`/`high` pause after `plan.md`.
Flags: `--pause-after-plan` (always pause), `--auto` (explicit classifier-gated
continuation; does not override medium/high), `--force-implement` (continue despite
medium/high, recorded), `--risk <level>` (override → `overridden_by_user`). The
computed risk is injected into the plan's Risk Assessment. See ADR-0014 (amends 0003),
0005, 0011.

Decision-encoding schema (from ADR-0014):

```json
"risk": { "level": "low|medium|high", "reasons": [],
          "auto_continue_allowed": true, "overridden_by_user": false }
```

## Acceptance criteria

- [ ] Low-risk task auto-continues through implement + verify
- [ ] Medium and high pause after plan → `planned` with a risk-gated `outcome_reason`
- [ ] `--pause-after-plan` always pauses; `--force-implement` continues despite medium/high (recorded); `--risk` override honored with `overridden_by_user: true`
- [ ] Same inputs → same Risk Level (deterministic, no model call)
- [ ] Weak/absent verification raises the risk
- [ ] `risk{}` is recorded in `metadata.json`; Risk Assessment appears in `plan.md`

## Blocked by

- Issue 03 (`issues/03-profiling-command-detection.md`)
- Issue 05 (`issues/05-planning-phase-prompts.md`)

## Comments

The deterministic `risk.py` classifier, the `decision_gate.py` Decision Gate,
the CLI flags (`--pause-after-plan`, `--auto`, `--force-implement`, `--risk`),
and the `runner.py` wiring (pre-plan classification -> plan Phase ->
post-plan re-classification with plan-predicted files -> Decision Gate ->
implement/verify or pause) were already present in the working tree
(from `src/ai_factory/{risk,decision_gate,runner,cli,report,prompts}.py`),
including `## 12. Risk Assessment` in the plan contract and the Risk
Assessment section leading `report.md`, but had **zero test coverage** — this
session added `tests/test_risk_aware_lifecycle.py` (20 tests) to lock in and
verify every acceptance criterion:

- `risk.classify()` tested directly as a pure function: low/medium/high per
  domain (auth_authz, broad_refactor, db_migrations via predicted files),
  determinism (same inputs -> same result), and the weak-verification bump
  (only when a risky domain is already matched; a domain-free task stays
  `low` even with no verification commands).
- `decision_gate.decide()` tested directly: low auto-continues; medium/high
  pause by default; `--pause-after-plan` always pauses (even low risk);
  `--force-implement` overrides medium/high (recorded); `--auto` does **not**
  override medium/high.
- End-to-end via the CLI against real temp git repos + the Fake Agent:
  low-risk task auto-continues through implement/verify to
  `implemented_verified`/`implemented_degraded`; a high-risk task (OAuth
  login) pauses after `plan.md` with outcome `planned` and a risk-gated
  `outcome_reason`, `implement`/`verify` left `not_executed`;
  `--pause-after-plan` pauses a low-risk task; `--force-implement` continues
  a high-risk task and records `force_implement_used`; `--auto` does not
  unpause a high-risk task; `--risk high` override is honored with
  `overridden_by_user: true`; an invalid `--risk` value is refused by
  argparse; `risk{}` is present with the full decision-encoding schema on
  every run.

Full suite: `pytest` — 83 passed (63 pre-existing + 20 new). `ruff check` and
`mypy src` both clean. Only issue 06's own acceptance criteria were touched;
no other issues were started. The `--auto` open question from the handoff
was left as specified in the PRD/ADR-0014 (explicit form of the
classifier-gated default; does not override medium/high) — no flip was
needed or made.

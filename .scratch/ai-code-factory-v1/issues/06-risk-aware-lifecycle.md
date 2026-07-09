# Risk-aware lifecycle — deterministic classifier + Decision Gate + flags

Status: ready-for-agent

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

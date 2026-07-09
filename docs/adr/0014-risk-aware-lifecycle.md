# Risk-aware lifecycle: deterministic risk classification gates automatic implementation

> **Amends ADR-0003.** Replaces "automation runs straight through by default" with
> risk-gated continuation.

The lifecycle gains a `risk_classify` Phase after `profile` and a **Decision Gate**
after `plan`:

```
profile → risk_classify → plan → [decision gate] → implement → verify → fix-loop → [review] → report
```

**Default behavior:** automation continues past planning **only for low-risk
tasks**; medium/high-risk tasks pause after `plan.md` and require explicit human
continuation.

```
low:          profile → risk_classify → plan → implement → verify → report
medium/high:  profile → risk_classify → plan → pause
```

This encodes the agentic-engineering vs vibe-coding distinction: automate
implementation only when a change is local and verifiable; pause for human judgment
when it touches architecture, security, data, migrations, infrastructure, broad
refactors, or has weak verification.

**Risk levels — `low | medium | high`** (criteria: blast radius, requirement
clarity, verification availability, and risky domains — auth/authz,
security/secrets, DB migrations, data mutation/deletion, infra/CI/CD/Terraform/K8s,
payments/billing, public API contract, broad refactor/architecture).

**CLI:**
- `--pause-after-plan` — always stop after planning, regardless of risk.
- `--auto` — explicitly allow classifier-gated continuation (proceeds only when the
  classifier permits, i.e. low); does not override medium/high.
- `--force-implement` — continue despite medium/high risk (advanced/unsafe;
  recorded).
- `--risk <low|medium|high>` — user override of the computed level (sets
  `overridden_by_user`).

**Deterministic, factory-owned classifier (NOT LLM-dependent in v1)** — parallels
ADR-0005. Inputs: task-text keywords, repo profile, plan-predicted changed files
(if available at the gate), available verification commands, presence/absence of
tests, and risky file/path patterns. The model may *comment* on risk in `plan.md`,
but the automation decision is factory-owned and deterministic.

**Metadata / report / plan impact:** `metadata.json` records
`risk {level, reasons[], auto_continue_allowed, overridden_by_user}`; the `planned`
outcome now covers three cases distinguished by `outcome_reason`
(`--pause-after-plan`, risk-gated pause, manual mode). `report.md` gains a **Risk
Assessment** section near the top; the plan contract gains `## 12. Risk Assessment`.

**Positioning:** ai-factory is *a local, repo-portable agentic engineering harness
that uses AI agents inside a deterministic safety, planning, verification, and
reporting workflow* — not an unchecked autonomous coding bot.

## Considered Options

- **Risk-gated default** (chosen).
- **Straight-through by default** (former ADR-0003 rule) — rejected: treats every
  task as low-risk and blurs the vibe-coding/agentic-engineering line.
- **LLM-decided risk gate** — rejected for v1: the automation decision must be
  deterministic and factory-owned.

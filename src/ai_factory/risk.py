"""Deterministic, factory-owned Risk Classification (ADR-0014, CONTEXT.md: Risk
Classification, Risk Level).

No model call, ever. `classify()` computes a Risk Level (`low` | `medium` |
`high`) plus `reasons[]` purely from task text, the Repo Profile, and
plan-predicted changed files -- the same inputs always produce the same level
(PRD acceptance: deterministic risk).

Risky domains (ADR-0014): auth/authz, security/secrets, DB migrations, data
mutation/deletion, infra/CI-CD/Terraform/K8s, payments/billing, public API
contract, broad refactor/architecture. The first six are treated as high-risk
domains on their own; public-API-contract and broad-refactor are medium-risk
on their own. Weak/absent verification (no commands detected, or no `test`
command) raises the risk by one tier -- but only for a task that already
touches a risky domain. A domain-free task (e.g. a doc tweak) stays `low` even
when the target repo has no detectable verification, matching the existing
"no verification commands -> degraded, not refused" behavior of the
Verification Gate (that Gate, not the Decision Gate, is what flags the lack of
verification loudly).
"""

from __future__ import annotations

import re

_DomainSpec = tuple[tuple[str, ...], tuple[str, ...]]

# name -> (task-text keywords, path substrings). Matched case-insensitively
# against the task text and against each plan-predicted file path.
_DOMAINS: dict[str, _DomainSpec] = {
    "auth_authz": (
        ("auth", "login", "logout", "authoriz", "authentic", "oauth", "sso", "rbac", "permission"),
        ("auth", "login", "session", "permission", "rbac"),
    ),
    "security_secrets": (
        ("secret", "password", "credential", "encrypt", "vulnerab", "security", "api key"),
        ("secret", "credential", ".env", ".pem", ".key"),
    ),
    "db_migrations": (
        ("migration", "migrate", "schema change", "alter table"),
        ("migrations/", "alembic/", ".sql"),
    ),
    "data_mutation_deletion": (
        ("delete", "drop table", "truncate", "purge", "destroy", "remove all", "wipe"),
        (),
    ),
    "infra_cicd": (
        ("terraform", "kubernetes", "k8s", "ci/cd", "cicd", "github actions", "pipeline", "dockerfile", "deploy", "infra"),
        ("terraform/", ".github/workflows/", "dockerfile", "k8s/", "helm/"),
    ),
    "payments_billing": (
        ("payment", "billing", "invoice", "stripe", "checkout", "credit card", "subscription"),
        ("billing/", "payments/", "stripe"),
    ),
    "public_api_contract": (
        ("public api", "api contract", "breaking change", "external api"),
        ("openapi", "swagger", "api/v"),
    ),
    "broad_refactor": (
        ("refactor", "rewrite", "redesign", "overhaul", "restructure", "architecture"),
        (),
    ),
}

# These, on their own, classify as `high`; the rest classify as `medium`.
_HIGH_DOMAINS = frozenset(
    {
        "auth_authz",
        "security_secrets",
        "db_migrations",
        "data_mutation_deletion",
        "infra_cicd",
        "payments_billing",
    }
)

_LEVELS = ("low", "medium", "high")


def _bump(level: str) -> str:
    index = _LEVELS.index(level)
    return _LEVELS[min(index + 1, len(_LEVELS) - 1)]


def _matched_domains(task: str, predicted_files: tuple[str, ...]) -> set[str]:
    task_lower = task.lower()
    files_lower = [f.lower() for f in predicted_files]
    matched: set[str] = set()
    for name, (keywords, path_substrings) in _DOMAINS.items():
        if any(keyword in task_lower for keyword in keywords):
            matched.add(name)
            continue
        if path_substrings and any(
            substring in file_path for file_path in files_lower for substring in path_substrings
        ):
            matched.add(name)
    return matched


def classify(
    task: str, profile: dict, predicted_files: list[str] | None = None
) -> tuple[str, list[str]]:
    """Compute `(level, reasons)` for `task` against `profile`, optionally
    informed by `predicted_files` (plan-predicted changed files, available
    once `plan.md` exists). Deterministic: the same arguments always return
    the same result."""
    domains = _matched_domains(task, tuple(predicted_files or ()))
    reasons: list[str] = []

    if domains & _HIGH_DOMAINS:
        level = "high"
        reasons.append("touches high-risk domain(s): " + ", ".join(sorted(domains & _HIGH_DOMAINS)))
    elif domains:
        level = "medium"
        reasons.append("touches risky domain(s): " + ", ".join(sorted(domains)))
    else:
        level = "low"

    commands = profile.get("commands") or {}
    has_tests = "test" in commands
    degraded = bool(profile.get("degraded", not commands))
    weak_verification = degraded or not has_tests

    if weak_verification and domains:
        reasons.append(
            "weak or absent verification for a task touching risky domain(s) -- raises the risk"
        )
        level = _bump(level)
    elif weak_verification:
        reasons.append(
            "no test command detected, but no risky domain matched -- risk stays low"
        )

    if not reasons:
        reasons.append("no risky keywords/paths detected and verification is available")

    return level, reasons


def render_pre_plan_context(level: str, reasons: list[str]) -> str:
    """Render the Factory's own pre-plan risk assessment as Prompt Bundle
    `extra_context` (CONTEXT.md: Prompt Bundle), so the Planning Agent can
    incorporate it into `## 12. Risk Assessment` -- purely informational; the
    automation continuation decision is computed by the Factory, never by the
    agent."""
    lines = [
        "The Factory has already computed its own deterministic, pre-plan Risk",
        f"Level for this task: **{level}**.",
        "",
        "Reasons:",
        *[f"- {reason}" for reason in reasons],
        "",
        "This is informational only -- feel free to reference it in your own "
        "`## 12. Risk Assessment` commentary, but the Factory will recompute "
        "the authoritative Risk Level after this plan is written (now also "
        "considering the files you list in `## 6. Affected Files & Areas`), "
        "and that -- not your commentary -- is what gates automatic "
        "continuation into implementation.",
    ]
    return "\n".join(lines)


_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_PATH_LIKE_RE = re.compile(r"[./]")


def extract_predicted_files(plan_text: str, heading: str = "## 6. Affected Files & Areas") -> list[str]:
    """Best-effort, deterministic extraction of file/path-like backtick-quoted
    tokens from the plan's Affected Files & Areas section, for the Decision
    Gate's risk re-computation. Returns `[]` if the heading is absent or no
    path-like tokens are found -- this is advisory input, not a hard
    requirement (ADR-0014: "if available at the Decision Gate")."""
    start = plan_text.find(heading)
    if start == -1:
        return []
    start += len(heading)
    next_heading = plan_text.find("\n## ", start)
    section = plan_text[start : next_heading if next_heading != -1 else len(plan_text)]
    candidates = _BACKTICK_RE.findall(section)
    return [c for c in candidates if _PATH_LIKE_RE.search(c)]

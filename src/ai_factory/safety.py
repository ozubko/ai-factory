"""The Command Deny-list (ADR-0007, CONTEXT.md: Command Deny-list).

Applied to every command the Factory itself runs — Verification Gate commands
from CLI flags, `factory.toml`, declared `package.json`/`Makefile` scripts, or
ecosystem heuristics. A match refuses the Run with an explicit message; it never
warn-and-continues, because the whole point is that a poisoned script can't do
damage through the gate.
"""

from __future__ import annotations

import re

# Patterns from ADR-0007, matched against the full command string. Deliberately
# broad (e.g. `rm -rf` in either flag order) rather than an exact-string match,
# since the gate must catch the intent, not one exact spelling.
_DENY_PATTERNS: tuple[str, ...] = (
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\b",
    r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f[a-z]*d[a-z]*\b",
    r"\bgit\s+clean\s+-[a-z]*d[a-z]*f[a-z]*\b",
    r"\bgit\s+push\b",
    r"\bgit\s+branch\s+-D\b",
    r"\bdocker\s+system\s+prune\b",
    r"\bdropdb\b",
    r"\bterraform\s+apply\b",
    r"\bkubectl\s+delete\b",
)

_COMPILED = tuple(re.compile(pattern) for pattern in _DENY_PATTERNS)


class DeniedCommandError(RuntimeError):
    """Raised when a factory-run command matches the Command Deny-list. The Run
    is refused and the command is never executed (ADR-0007)."""


def check_command(command: str) -> None:
    """Raise `DeniedCommandError` if `command` matches the Command Deny-list;
    otherwise return `None`. Deterministic: the same command string always
    produces the same result."""
    for pattern in _COMPILED:
        if pattern.search(command):
            raise DeniedCommandError(
                f"command '{command}' matches the Command Deny-list and was "
                "refused, not executed (ADR-0007)"
            )


# Secret-value redaction (ADR-0007, ADR-0010): applied to Repository Instructions
# content before it is embedded in any Prompt Bundle, so a secret accidentally
# committed to a README/AGENTS.md can't leak into a prompt or report. Errs
# toward over-redacting prose rather than risking a missed real secret.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]+"),
)


def redact_secrets(text: str) -> str:
    """Replace secret-looking substrings in `text` with `[REDACTED]`.
    Deterministic: the same text always produces the same result. This is a
    best-effort filter over Repository Instructions content, not a substitute
    for the presence-only secret-file detection in `profiling.py`."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted

"""Run ID generation (CONTEXT.md: Run ID — task slug + short hash)."""

from __future__ import annotations

import re
import uuid


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "task"


def generate_run_id(task: str) -> str:
    return f"{slugify(task)}-{uuid.uuid4().hex[:8]}"

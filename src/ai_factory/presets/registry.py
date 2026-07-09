"""Named Backend Presets (ADR-0006). Vendors are data, not code.

Command templates use `{placeholder}` tokens rendered by `SubprocessBackend`.
Repo config may only select a preset by name — it can never define a template
(ADR-0007/0008); this registry is the sole source of templates in v1.
"""

PRESETS: dict[str, str] = {
    "fake": (
        "{python} -m ai_factory.presets.fake_agent "
        "--phase {phase} --output {output_path}"
    ),
    # Test-only preset: makes the Fake Agent misbehave during read-only Phases
    # (plan/review), so the Factory's Contract Violation detection can be
    # exercised end-to-end (CONTEXT.md: Contract Violation).
    "fake-readonly-violator": (
        "{python} -m ai_factory.presets.fake_agent "
        "--phase {phase} --output {output_path} --mutate-readonly"
    ),
}

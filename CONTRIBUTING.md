# Contributing to AI Hub

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

Thank you for contributing. Start with the
[Architecture Overview](docs/ARCHITECTURE.md),
[Glossary](docs/GLOSSARY.md), and the relevant accepted ADR.

## Before changing code

- Preserve the frozen boundary: `core/`, the base Router, existing health/score
  routers, and current Provider implementations are bug-fix only.
- Write a Proposed ADR before changing an architecture contract, serialized
  schema, or frozen boundary.
- Keep provider communication inside Bridge implementations.
- Keep reader-facing documentation synchronized in English and Simplified
  Chinese.
- Never commit credentials, access tokens, cookies, or private runtime output.

## Adding a provider

1. Create a new `providers/<name>/` package.
2. Implement the stable Provider contract and reuse an existing Bridge.
3. Return a four-state `HealthReport` from new health implementations.
4. Register only declared capabilities from `core.capabilities.CAPABILITIES`.
5. Add the provider contract and capability-consistency tests.

See the [Provider Specification](docs/PROVIDER_SPEC.md) for a complete example.

## Changing the pipeline

Workflow behavior belongs in focused files under `planner/` or
`planner/stages/`. Preserve these rules:

- stages do not mutate ExecutionEvent facts;
- metadata serialization has one canonical implementation;
- inspection methods do not execute stages or predicates;
- schema changes require stability tests and an ADR;
- source inspection, AST parsing, and hidden callable inference are out of scope
  unless a future accepted ADR explicitly changes that policy.

## Tests

Run focused tests first, then the non-live regression suite:

```bash
python -m pytest tests/test_provider_contract.py -q
python -m pytest tests/ -x -q \
  --deselect "tests/test_benchmark.py" \
  --deselect "tests/test_cli_plan_json.py"
```

Mark tests that require real providers with `@pytest.mark.live`. Unit and
contract tests must not require a developer's API keys or signed-in session.

## Pull request checklist

- [ ] The change has a focused scope and a clear rationale.
- [ ] Frozen files are untouched, or the change is an explicitly justified bug fix.
- [ ] New architecture behavior has a reviewed ADR.
- [ ] Focused tests and the non-live regression suite pass.
- [ ] New Provider capabilities exist in the canonical capability registry.
- [ ] Public serialized keys have stability coverage.
- [ ] English and Simplified Chinese reader docs are synchronized.
- [ ] No credentials or private data are present in the diff.

## Documentation language policy

The unsuffixed reader-facing file is English; the paired Chinese file uses
`.zh-CN.md`. ADRs, external reviews, handoffs, and version artifacts remain in
their original language as immutable historical records. See the
[documentation index](docs/README.md).

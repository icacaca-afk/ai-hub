# ADR-0037: Clean Installation and Deterministic Demo Execution

| Field | Value |
|-------|-------|
| Status | Implemented; review pending |
| Date | 2026-08-20 |
| Decider | User |
| Related | ADR-0008 (Core Freeze), ADR-0034 (CLI Pipeline Introspection) |

## Context

The `multi-agent-loop` Phase 0 assessment requires delivery claims to be tied
to executable evidence rather than agent assertions. Applying that rule to AI
Hub exposed two release-path failures:

1. editable installation works because it imports directly from the checkout,
   but a wheel omits `planner.metrics`, `planner.stages`, and
   `providers.claude_cli` because `pyproject.toml` lists packages manually;
2. `ai-hub plan` may select an installed live CLI provider and wait for its
   full timeout, so there is no deterministic account-free end-to-end command;
3. distribution metadata reports `0.0.1` while runtime inspection reports
   `1.0.13`, so a wheel cannot prove which milestone it contains;
4. MCP `list_providers` performs external availability and authentication
   checks by default, while its contract client blocks directly on `readline`,
   so the suite can wait indefinitely instead of enforcing its timeout.

## Decision

### Recursive package discovery

Setuptools will discover all packages below the maintained top-level package
names. A contract test will guard the currently required nested packages, and
the release gate will build and install a non-editable wheel outside the source
tree before running CLI smoke tests.

### Explicit provider pinning

`ask` and `plan` accept `--provider NAME`. The option creates a new registry
containing only the named provider; it does not change Router scoring,
fallbacks, health rules, or the default command behavior.

The following commands become the deterministic local acceptance path:

```text
ai-hub ask "hello" --provider demo
ai-hub plan "say hello then summarize it" --provider demo --json
ai-hub pipeline inspect --json
```

An unknown provider, missing provider value, or duplicate provider option exits
with code 1 before any Provider or Bridge is executed.

### Optional test dependencies

The base wheel remains dependency-light. The `test` extra declares pytest and
the compatible MCP SDK major version (`mcp>=1,<2`) so the test environment is
reproducible without forcing MCP dependencies on normal CLI users.

### Single version source

`cli/version.py` defines `__version__`. Setuptools reads that attribute as
dynamic distribution metadata, and pipeline inspection imports the same value.
The `cli` directory is a regular package rather than an implicit namespace so
an unrelated installed `cli.py` module cannot shadow the AI Hub entry point.

### Bounded MCP discovery

MCP `list_providers` returns registered metadata without probing by default;
`available` is `null` and `availability` is `unchecked`. A caller may request
`probe_availability=true` explicitly. The MCP contract client drains stdout in
a daemon reader thread and waits through a bounded queue, so its timeout is a
real deadline even when the server stops producing lines.

## Invariants

- No files under `core/`, existing Router implementations, or existing
  Provider implementations are modified.
- Provider communication still crosses the Provider/Bridge boundary.
- Default routing remains unchanged when `--provider` is absent.
- JSON modes emit JSON only.
- A successful editable install is not accepted as wheel evidence.

## Non-goals

- Implementing the full persistent state machine proposed by
  `multi-agent-loop`.
- Automatically approving releases or replacing human review gates.
- Adding live-provider calls to the default test suite.
- Changing Provider priority, health, fallback, or timeout semantics.

## Verification gate

The change is ready only when all of the following have exit code 0:

1. focused packaging and provider-selection tests;
2. non-editable wheel installation in a clean virtual environment;
3. imports of all required nested packages from outside the repository;
4. the three deterministic CLI acceptance commands above;
5. frozen-boundary and existing CLI/Planner regression tests.
6. distribution metadata equals runtime version `1.0.13`;
7. the complete MCP stdio contract suite finishes within its response bounds.

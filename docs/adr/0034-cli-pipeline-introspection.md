# ADR-0034: CLI Pipeline Introspection

| Field | Value |
|-------|-------|
| Status | Proposed |
| Date | 2026-08-17 |
| Decider | User + external architecture review |
| Supersedes | — |
| Superseded by | — |
| Related | ADR-0031 (Metadata Serialization), ADR-0032 (Pipeline Introspection), ADR-0033 (Predicate API) |

## 1. Context

### 1.1 Background

V1.0.11 introduced side-effect-free structural introspection:

```text
ExecutionPipeline
  → describe()
  → PipelineDescriptor
  → serialize_pipeline()
  → dict
  → JSON
```

V1.0.12 introduced explicit predicate semantics:

```text
ConditionStage
  → describe_predicate()
  → PredicateDescriptor
  → serialize_predicate()
  → dict
```

Both APIs are Python-facing. A user of the installed `ai-hub` command still
cannot inspect the default runtime pipeline or see which declared predicate is
associated with a condition stage.

### 1.2 Problem

Pipeline structure and predicate semantics deliberately have separate canonical
schemas. Joining predicates directly into `serialize_pipeline()` would break
the V1.0.11 schema-stability contract and make the metadata layer aware of
runtime stage instances.

The CLI needs a presentation model that can join these two read-only views while
preserving their ownership boundaries:

- pipeline structure remains owned by `ExecutionPipeline.to_dict()`;
- predicate semantics remain owned by `serialize_predicate()`;
- the relationship is expressed with stable stage IDs (`pre:N` / `post:N`);
- no callable is evaluated or source-inspected.

### 1.3 Goals

- Add `ai-hub pipeline inspect [--json]`.
- Inspect the default pipeline assembled by the current CLI runtime.
- Provide deterministic human-readable and JSON output.
- Join declared predicate semantics at the CLI presentation layer only.
- Expose a pure `build_pipeline_inspection(pipeline)` function so configured or
  custom pipelines can use the same presentation model in Python.
- Keep introspection side-effect-free.

### 1.4 Non-goals

- No changes to `PipelineDescriptor` or `serialize_pipeline()`.
- No predicate expression engine, parser, AST, bytecode, lambda, or source
  introspection.
- No pipeline execution, editing, persistence, visualization, DOT, or Mermaid.
- No loading arbitrary Python factories or dotted import paths from CLI input.
- No new pipeline configuration format.
- No schema versioning framework; that remains deferred to V1.1.
- No changes to frozen Core, existing Router implementations, or Providers.

## 2. Decision

### 2.1 Command grammar

The command is a namespace with one initial subcommand:

```text
ai-hub pipeline inspect
ai-hub pipeline inspect --json
```

Behavior is fixed as follows:

| Input | Result |
|-------|--------|
| `pipeline inspect` | Human-readable pipeline structure |
| `pipeline inspect --json` | JSON presentation document |
| `pipeline` | Usage on stderr/stdout and exit 1 |
| `pipeline unknown` | Error + usage and exit 1 |
| `pipeline inspect --unknown` | Error + usage and exit 1 |
| `pipeline inspect --help` | Usage and exit 0 |

The nested form avoids overloading the existing `ai-hub inspect`, which is
reserved for persisted or in-process Plan inspection.

### 2.2 CLI module boundary

Create `cli/pipeline_inspect.py` with four responsibilities:

1. `build_pipeline_inspection(pipeline)` builds the presentation document.
2. `_build_default_pipeline()` constructs the current CLI default pipeline.
3. `_print_human(payload)` renders deterministic terminal output.
4. `cmd_pipeline(args, *, pipeline=None)` validates arguments and dispatches.

The optional `pipeline` keyword is dependency injection for tests and Python
callers. The console path omits it and receives the current default pipeline.

### 2.3 Presentation-only join

`build_pipeline_inspection()` starts with the canonical pipeline document:

```python
pipeline_data = pipeline.to_dict()
```

It then visits `pre_bridge_stages` and `post_bridge_stages` in order. A stage is
predicate-describable only when it exposes a callable `describe_predicate`
method. The CLI calls that method and serializes the returned descriptor with
the existing canonical `serialize_predicate()` function.

Each association uses the same structural ID rule as ADR-0032:

```json
{
  "stage_id": "post:1",
  "predicate": {
    "name": "bridge_succeeded",
    "description": "Continue only after a successful bridge call",
    "subject": "bridge_result.success"
  }
}
```

The join MUST NOT mutate `pipeline_data["stages"]`. Predicates remain a
separate top-level list so the canonical pipeline schema is byte-for-byte equal
to `pipeline.to_dict()`.

### 2.4 JSON output

The JSON presentation document is:

```json
{
  "runtime_version": "1.0.13",
  "pipeline": {
    "name": "default",
    "stages": [],
    "edges": [],
    "has_router": true,
    "has_quota": false,
    "has_hooks": false
  },
  "predicates": []
}
```

Constraints:

- `runtime_version` identifies the producing CLI release, not a schema.
- No `schema_version` is introduced in V1.0.13.
- `pipeline` equals `pipeline.to_dict()` exactly.
- `predicates` is ordered by pipeline position: all pre stages, then all post
  stages, each by index.
- JSON uses the shared `metadata_serialization.to_json()` policy
  (`ensure_ascii=False`, indent 2).
- JSON mode emits JSON only; no heading, hint, or status text is mixed into
  stdout.

### 2.5 Human output

Human output uses stable IDs and has three sections:

```text
AI Hub Pipeline — v1.0.13

Pipeline: default
Router: configured
Quota: not configured
Hooks: disabled

Stages:
  [pre:0] route (router)
  [bridge] __bridge__ (bridge)
  [post:0] metrics (metrics)

Predicates:
  (none declared)

Edges:
  pre:0 -> bridge (pre_to_bridge)
  bridge -> post:0 (bridge_to_post)
```

For declared predicates, the `Predicates` section prints stage ID, name,
subject, and description. Empty subject/description values are omitted from the
human view but preserved in JSON.

### 2.6 Default pipeline source

The command describes the same default pipeline shape used by the planning CLI.
It may reuse the existing CLI registry builder and runtime dependencies, but it
MUST NOT execute a Task, refresh provider health, or invoke a Bridge.

This release does not accept arbitrary pipeline factory paths. Such loading
would create an avoidable code-execution surface and a configuration contract
that does not yet exist.

### 2.7 Side-effect and safety invariants

The following are hard constraints:

- `pipeline.run()` is never called.
- Predicate callables are never evaluated.
- No `inspect.getsource`, `inspect.getsourcelines`, `ast.parse`, `ast.walk`,
  `dis.dis`, or bytecode inspection.
- No Provider/Bridge communication.
- No mutation of pipeline stage lists, descriptors, or serialized dictionaries.
- Duplicate stage names remain unambiguous because associations use stable IDs.

## 3. Consequences

### 3.1 Positive

- Users can inspect the default execution boundary without running a task.
- Structure and predicate semantics become useful from the installed CLI.
- Canonical schemas remain stable and independently owned.
- Stable IDs support duplicate stage names and deterministic automation.
- The pure presentation builder is reusable by future adapters without moving
  CLI concerns into `planner/`.

### 3.2 Negative

- The console command inspects only the built-in/default runtime pipeline;
  there is not yet a CLI configuration contract for custom pipelines.
- The CLI presentation has a second top-level document around the canonical
  pipeline output.
- Runtime version remains a literal until package version metadata is unified.

### 3.3 Mitigation

- Python callers can pass custom pipelines directly to
  `build_pipeline_inspection()`.
- The wrapper is explicit and tested; it does not silently change canonical
  metadata.
- Package-version unification remains a maintenance task and is not hidden
  inside this feature.

## 4. Interface changes

| Change | Type | Backward compatible | Scope |
|--------|------|---------------------|-------|
| `ai-hub pipeline inspect` | Add | Yes | `cli/` |
| `ai-hub pipeline inspect --json` | Add | Yes | `cli/` |
| `build_pipeline_inspection(pipeline)` | Add | Yes | `cli/pipeline_inspect.py` |
| Main command registration/help | Modify | Yes | `cli/main.py` |

## 5. Frozen boundary check

| Path | Modification | Result |
|------|--------------|--------|
| `core/` | None | Frozen boundary preserved |
| `router/router.py` | None | Frozen boundary preserved |
| `router/health_router.py` | None | Frozen boundary preserved |
| `router/score_router.py` | None | Frozen boundary preserved |
| `providers/` | None | Frozen boundary preserved |
| `planner/` | None | Canonical V1.0.11/V1.0.12 APIs consumed unchanged |
| `cli/pipeline_inspect.py` | New | Presentation boundary |
| `cli/main.py` | Command registration/help only | Experimental CLI boundary |

## 6. Test plan

Create `tests/test_cli_pipeline_inspect.py` covering:

1. top-level JSON keys and `runtime_version`;
2. canonical `pipeline` equality;
3. empty predicate list;
4. pre/post predicate stable IDs and deterministic order;
5. duplicate stage names remain unambiguous;
6. predicate serializer output is preserved under `predicate`;
7. no predicate evaluation side effect;
8. no pipeline execution side effect;
9. no source/AST/bytecode introspection;
10. human stage, predicate, and edge rendering;
11. omission of empty human predicate fields;
12. JSON-only stdout;
13. usage, help, unknown subcommand, and unknown flag exit behavior;
14. registration and usage text in `cli.main`;
15. frozen-boundary regression and existing introspection/predicate tests.

Focused validation:

```powershell
python -m pytest tests/test_cli_pipeline_inspect.py `
  tests/test_pipeline_introspection.py tests/test_predicate_api.py -q
```

Full regression:

```powershell
python -m pytest tests -x -q `
  --deselect tests/test_benchmark.py `
  --deselect tests/test_cli_plan_json.py
```

## 7. Rejected alternatives

### R-A: Embed predicates into `serialize_pipeline()`

Rejected because it breaks ADR-0032 schema stability and makes the canonical
metadata serializer inspect runtime stage instances.

### R-B: Add predicate fields to `PipelineDescriptor`

Rejected because structure and predicate semantics have different owners and
lifecycles. It would also require a V1.0.11 descriptor/schema migration.

### R-C: Accept a dotted Python factory path on the command line

Rejected because arbitrary imports create code-execution and configuration
contracts outside the scope of read-only introspection.

### R-D: Reuse `ai-hub inspect`

Rejected because that command already means Plan inspection. Overloading it
would make help, arguments, and error semantics ambiguous.

### R-E: Add graph visualization now

Rejected because V1.0.13 is presentation of existing data, not a visualization
engine. The stable JSON document is sufficient input for a later graph command.

## 8. Release gate

ADR-0034 remains `Proposed` until external architecture review. Implementation
may begin only after review findings are recorded and blocking issues are
resolved. Release requires focused tests, full regression, frozen-boundary
verification, version tag `v1.0.13`, and code review approval.

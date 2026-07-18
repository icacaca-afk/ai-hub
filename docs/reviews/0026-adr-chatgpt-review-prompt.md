# V1.0.6 StageDescriptor — ADR Review Prompt

## Context

We are building **AI Hub** — a local AI runtime evolved from a Provider Router to an AI Operating System / Agent Runtime. The V1.0.x cycle focuses on the **ExecutionPipeline** architecture: a decorator-based, context-driven pipeline that replaces the V0.x Router subclass hierarchy.

**Strict Core Freeze:** `core/`, `router/router.py`, and `providers/` MUST NOT be modified. All extension happens in `planner/`.

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.3 ADR-0022 RetryStage + ADR-0023 CheckpointStage (9.95/10 FINAL)
- V1.0.4 ADR-0024 ConditionStage (ADR 9.9/10 + Code 9.95/10)
- **V1.0.5 ADR-0025 PipelineHooks (ADR 9.9/10 + Code 9.93/10) — Accepted (34645a8)**
- **V1.0.6 ADR-0026 StageDescriptor — DRAFT (a535b3c), under review**

## What to Review (V1.0.6 ADR)

**File:** `docs/adr/0026-stage-descriptor.md` (506 lines)

**Core Proposal:**

Introduce `StageDescriptor` — a frozen dataclass that describes Stage metadata, replacing the string-based `stage.name` convention in `Pipeline.run()`.

```python
@dataclass(frozen=True)
class StageDescriptor:
    name: str                    # Unique ID
    version: int = 1
    role: str = "stage"          # "stage" | "checkpoint" | "condition" | "retry" | "metric"
    capabilities: Set[str] = field(default_factory=set)
    idempotent: bool = True
    has_side_effects: bool = False
    always_run_after_stop: bool = False  # V1.0.4 Checkpoint key
    experimental: bool = False
    description: str = ""
    owner: str = "ai-hub"
```

**Key Decisions:**

1. **Replace string-based identification** — `Pipeline.run()` uses `stage.descriptor.always_run_after_stop` instead of `stage.name == "checkpoint"` (eliminates V1.0.4's only duck-typing coupling).

2. **5 existing Stages** (Route / Metrics / Retry / Checkpoint / Condition) get a `descriptor` ClassVar.

3. **Hook signature extension** (Backwards-compatible):
   ```python
   def before_stage(ctx, stage_name: str, descriptor: Optional[StageDescriptor] = None): ...
   ```

4. **V1.0.x compatibility** — Old Stages without `descriptor` get a default `StageDescriptor(name=stage.name)` via factory function.

5. **`frozen=True`** — Descriptor is immutable metadata.

## Motivation (Why Now?)

From V1.0.5 ChatGPT 9.93/10 review:
> "我建议 V1.0.6 聚焦于: **StageDescriptor**: 用统一描述对象替代基于 stage.name 的字符串约定, 为未来扩展（分类、能力标签、可观测性）打基础。"

V1.0.4 had this code:
```python
# planner/pipeline.py V1.0.4 — the only coupling ChatGPT flagged
if stage.name == "checkpoint" and hasattr(stage, "store"):
    ctx = stage(ctx)
```

V1.0.6 replaces it with:
```python
if stage.descriptor.always_run_after_stop:
    ctx = stage(ctx)
```

## Specific Questions

1. **Field set breadth:** Is `name / version / role / capabilities / idempotent / has_side_effects / always_run_after_stop / experimental / description / owner` the right set? Which V1.0.6 MUST, which V2?

2. **Pipeline decoupling depth:** Using `descriptor.always_run_after_stop` — is this sufficient? Should we add a second check like `descriptor.role == "checkpoint"`?

3. **Hook signature extension:** Adding `descriptor: Optional[StageDescriptor] = None` parameter — correct? Or should we use `**kwargs` to avoid signature inflation?

4. **Stage base class:** ADR introduces an optional `Stage` base class but doesn't require inheritance. Should we use `Protocol` instead? Or remove the base class entirely and rely only on `_get_descriptor` factory?

5. **`role` as string vs Enum:** ADR uses string for V1.0.6, proposes Enum for V2. Correct sequencing? Or should we go directly to `class Role(str, Enum)`?

6. **Capabilities as Set vs List:** `Set[str]` to avoid duplicates. Reasonable?

7. **V1.0.x compatibility:** Default `StageDescriptor(name=stage.name)` for old Stages — but V1.0.4's `always_run_after_stop` defaults to `False`, which would BREAK the abort-after-checkpoint behavior! How should we handle this? Options:
   - (a) Migration: add `descriptor` to all V1.0.x Stages in V1.0.6
   - (b) Smart factory: detect CheckpointStage via `hasattr(stage, "store")` and inject `always_run_after_stop=True` (re-introduces coupling)
   - (c) Stage-level opt-in: `CheckpointStage` declares descriptor in V1.0.6 explicitly

8. **Test coverage:** 10 + 5 + 3 tests sufficient? Need stress / property-based?

9. **Runtime Contract sync:** §9.1 Stage Descriptor section — should we have a separate `docs/stage-descriptor.md`?

10. **V1.0.7 Runtime Metadata Schema unity** (ChatGPT 9.93/10 hint): Should this ADR include `ctx.metadata` schema (condition_eval / server_metrics / stopped_by)?

## Scoring Rubric

- 9.0+ = Production-quality, ship as-is
- 9.5+ = Minor polish suggestions (non-blocking)
- 9.9+ = Exceptional, with optional roadmap hints

## Deliverables

Please return:
1. **Score** (0-10) with rationale
2. **Adopt-or-defer table** for each suggestion (Critical / Non-blocking / Defer)
3. **Recommended adjustments** (concrete, code-level)
4. **V1.0.7+ roadmap hints** (Stage Registry / Schema validation)
5. **Critical issue analysis** — especially around Q7 (V1.0.x CheckpointStage compat)

Thank you!

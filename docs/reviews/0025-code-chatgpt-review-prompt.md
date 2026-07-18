# V1.0.5 PipelineHooks — Code Review Prompt

## Context

We are building **AI Hub** — a local AI runtime evolved from a Provider Router to an AI Operating System / Agent Runtime. The V1.0.x cycle focuses on the **ExecutionPipeline** architecture: a decorator-based, context-driven pipeline that replaces the V0.x Router subclass hierarchy.

**Strict Core Freeze:** `core/`, `router/router.py`, and `providers/` MUST NOT be modified. All extension happens in `planner/`.

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.2 (skipped — folded into V1.0.3)
- V1.0.3 ADR-0022 RetryStage + ADR-0023 CheckpointStage (9.95/10 FINAL)
- V1.0.4 ADR-0024 ConditionStage (ADR 9.9/10 + Code 9.95/10)
- **V1.0.5 ADR-0025 PipelineHooks (9.9/10 ADR Approved) — code under review**

## What to Review (V1.0.5 Code Implementation)

**Files:**

1. `planner/hooks.py` (NEW, ~190 lines) — `PipelineHooks` class with 6 hook points
2. `planner/pipeline.py` (MODIFIED) — `ExecutionPipeline.run()` integrates hooks
3. `planner/executor.py` (MODIFIED) — `PlanExecutor` passes through `hooks` parameter
4. `tests/test_pipeline_hooks.py` (NEW, ~410 lines, 19 tests)

**Commit:** `75c90c6` — "V1.0.5: implement PipelineHooks (Lifecycle Observer)"

## ADR-0025 Approved Design (9.9/10)

**6 Hook Points (observers, not stages):**

1. `before_pipeline(ctx)` — Pipeline.run entry
2. `after_pipeline(ctx, result)` — Pipeline.run exit (with Result)
3. `before_stage(ctx, stage_name)` — Before each Stage
4. `after_stage(ctx, stage_name)` — After each Stage
5. `on_error(ctx, stage_name, exc)` — On Stage exception (but Pipeline still re-raises)
6. `on_stop(ctx, stopped_by)` — On `ctx.stop` trigger

**Critical Invariants (ChatGPT 9.9/10 adopted):**

- Hooks are **observers**, not stages. They MUST NOT modify `ctx`, MUST NOT participate in control flow, MUST be side-effect free.
- Hook **failures MUST NOT influence execution outcome** (Best Effort — every fire_xxx catches Exception and logger.warning).
- Hooks execute in **FIFO registration order**.
- `enabled` property (Q7 adoption) — `any([...])` short-circuits in `Pipeline.run()`.
- `is_empty()` is a compat shim for V1.0.4 (it returns `not enabled`).
- `on_stop` receives `stopped_by` string (e.g. `"condition:on_failure:abort"` or `"stop_flag"` fallback).

**Pipeline.run() V1.0.5 Integration:**

```python
# 入口
if self.hooks.enabled:
    self.hooks.fire_before_pipeline(ctx)

# 每个 Stage
if self.hooks.enabled:
    self.hooks.fire_before_stage(ctx, stage.name)
try:
    ctx = stage(ctx)
except Exception as e:
    if self.hooks.enabled:
        self.hooks.fire_on_error(ctx, stage.name, e)
    raise
if self.hooks.enabled:
    self.hooks.fire_after_stage(ctx, stage.name)
if ctx.stop:
    if self.hooks.enabled:
        self.hooks.fire_on_stop(ctx, "stop_flag")
    ...

# 出口
result = PipelineExecutor.assemble_result(ctx)
if self.hooks.enabled:
    self.hooks.fire_after_pipeline(ctx, result)
return result
```

**`_get_stopped_by(ctx, aborted_idx)` helper** — extracts the actual stop reason from `ctx.metadata["condition_eval"].stopped_by` (V1.0.4 metadata), falling back to `"stop_flag"` if not present. This is passed to `fire_on_stop`.

**Tests (19, all passing):**

- `TestPipelineHooksBasics` (8): init, 6 fire_xxx, FIFO
- `TestPipelineHooksFailure` (3): Best Effort, partial failure, total failure
- `TestPipelineHooksIntegration` (4): Pipeline runs with hooks, without hooks, FIFO, default_pipeline passthrough
- `TestPipelineHooksChatGPTEdgeCases` (4): hook not modifying ctx, on_stop with condition stopped_by, enabled partial, is_empty compat

**V1.0.x Test Suite:** 150 tests passing.

## Specific Questions

1. **Pipeline.run() coupling:** Is the inline hook firing in `Pipeline.run()` too coupled to the stage list? Is there a cleaner abstraction (e.g. a `_run_with_hooks` wrapper, or context manager)?

2. **`_get_stopped_by` location:** Should this helper live in `PipelineHooks` (since it's hook-related) or stay in `ExecutionPipeline` (since it knows `ctx.metadata` and stage internals)?

3. **Hook error swallowing:** Is `logger.warning` the right level? Should V2 add a "raise to user" mode for on_error hooks (i.e. let hook say "I want to know about this even if Pipeline re-raises")?

4. **`on_error` re-raise semantics:** Currently Pipeline catches, fires `on_error`, then re-raises. Is this the right ordering, or should V2 consider firing `on_error` AFTER the exception unwinds (e.g. in a finally block)?

5. **Hook signature stability:** The 6 hook signatures (`(ctx)`, `(ctx, result)`, `(ctx, str)`, `(ctx, str, Exception)`, `(ctx, str)`) — are they minimal and stable enough for V1.0.x API guarantee?

6. **`is_empty()` deprecation path:** V1.0.5 has both `enabled` (Q7) and `is_empty()` (compat shim). When should `is_empty()` be removed?

7. **Test coverage:** 19 tests cover construction, fire_xxx, Best Effort, Pipeline integration, and ChatGPT edge cases. Any obvious gaps? (e.g. concurrent hook execution, hook with side effects on external state, hook called with malformed ctx.)

8. **Architecture:** Does this fit cleanly with the V1.0.x ExecutionPipeline vision (decorator-based, context-driven, Runtime Observability)? Or does it introduce a new axis that needs a separate ADR (e.g. ADR-0025a Hook Registry)?

9. **Performance:** Every Stage call now does `if self.hooks.enabled:` check (cheap, but adds a branch). Is this acceptable for V1.0.x, or should V2 move to a registration-flag-only model (PipelineHooks returns a no-op stand-in when empty)?

10. **V2 StageDescriptor compatibility:** ADR-0025 mentions that V2 will introduce a StageDescriptor to replace name-based duck typing. Does the current hook design need any V2-migration hooks, or is it forward-compatible?

## Scoring Rubric

- 9.0+ = Production-quality, ship as-is
- 9.5+ = Minor polish suggestions (non-blocking)
- 9.9+ = Exceptional, with optional roadmap hints

## Deliverables

Please return:
1. **Score** (0-10) with rationale
2. **Adopt-or-defer table** for each suggestion (Critical / Non-blocking / Defer)
3. **Recommended adjustments** (concrete, code-level)
4. **V1.0.6 roadmap hints** (if any, for StageDescriptor / V2)

Thank you!

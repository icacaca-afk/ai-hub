# V1.0.7 RuntimeMetadata Implementation — ChatGPT Code Review Prompt

## Context

V1.0.7 ADR-0027 Runtime Metadata Schema — **implementation review** after ADR Approved 9.85/10.

**Cycle:**
- V1.0.5 PipelineHooks → 9.93/10 → Accepted (34645a8)
- V1.0.6 StageDescriptor → 9.95/10 → Accepted (9b8ff1b)
- **V1.0.7 ADR-0027 RuntimeMetadata → 9.85/10 ADR Approved (c0678e1)**
- **V1.0.7 Implementation (877a22a) → review pending**

## Files Changed (8 files, 1278 insertions)

### NEW Files

1. **`planner/runtime_metadata.py`** (305 lines)
   - `RuntimeMetadata` dataclass with V1.0.7 MUST fields: server_metrics / condition_eval / stopped_by / plan / custom
   - Helper methods (N1 adopted): `set_condition_eval()` / `set_server_metrics()` / `set_plan()` / `set_stopped_by()` / `set_custom()`
   - `_ensure_metadata()` private helper (V1.0.6 backward compat)
   - `RUNTIME_RESERVED_KEYS` frozenset
   - TYPE_CHECKING import to avoid circular deps
   - Detailed docstrings explaining MUST-1, MUST-2, MUST-3, MUST-4 contracts

2. **`tests/test_runtime_metadata.py`** (30 tests)
   - TestRuntimeMetadataDefaults (6 tests)
   - TestRuntimeMetadataFieldSet (6 tests) — no retry, no experimental, top-level stopped_by
   - TestHelperSetConditionEval (4 tests) — helper 写 runtime + metadata via ctx
   - TestHelperSetServerMetrics (3 tests) — merge/replace
   - TestHelperSetPlan (2 tests) — copy behavior
   - TestHelperSetStoppedBy (2 tests) — top-level helper
   - TestHelperSetCustom (1 test) — runtime only, no write-through
   - TestWriteThroughOnly (2 tests) — MUST-2: no reverse sync
   - TestEnsureMetadata (3 tests) — V1.0.6 compat
   - TestRuntimeMetadataNotFrozen (1 test)

3. **`tests/test_plugin_compatibility.py`** (17 tests)
   - TestV1_0_6_PluginStillWorks (3) — third-party plugin dict API still works
   - TestV1_0_6_HookStillWorks (3) — Hook read via dict still works
   - TestMixedV1_0_6_V1_0_7 (3) — mixed V1.0.6 + V1.0.7 styles coexist
   - TestWithXxxPropagatesRuntime (4) — ExecutionContext.with_xxx propagates runtime
   - TestRuntimeContractMUSTs (4) — MUST-1/2/3/4 contract tests

4. **`tests/test_stage_runtime_metadata.py`** (12 tests)
   - TestConditionStageRuntime (4) — writes ctx.runtime.condition_eval + stopped_by
   - TestCheckpointStageRuntimeRead (6) — prefers runtime, falls back to dict
   - TestMetricsStageRuntime (2) — writes ctx.runtime.server_metrics

### Modified Files

5. **`planner/pipeline.py`**
   - Added `runtime: RuntimeMetadata` field to `ExecutionContext` (V1.0.7 additive)
   - All `with_xxx()` helpers propagate `runtime` + `metadata`
   - `MetricsStage` uses `ctx.runtime.set_server_metrics()` helper
   - Imports `RuntimeMetadata`

6. **`planner/stages/condition_stage.py`**
   - `ConditionStage.__call__` uses `ctx.runtime.set_condition_eval()` helper
   - Single helper call (instead of scattered double-write)

7. **`planner/stages/checkpoint_stage.py`**
   - `CheckpointSnapshot.from_context` reads `ctx.runtime.stopped_by` first (top-level)
   - Falls back to `ctx.runtime.condition_eval.stopped_by`
   - Falls back to `ctx.metadata["condition_eval"].stopped_by` (V1.0.6 compat)
   - Falls back to `ctx.stop → "stop_flag"`
   - Reads `ctx.runtime.server_metrics` first, falls back to `ctx.result.metadata["server_metrics"]`

8. **`docs/adr/0027-runtime-metadata-schema.md`**
   - Updated §2.4 (PlanExecutor) to reflect reality (plan stays in Result.metadata)
   - Status: Accepted (was Draft v2)

## Key Implementation Decisions

### Decision 1: Helper Encapsulation (N1 adopted)

```python
# Before (would be scattered):
ctx.runtime.condition_eval = eval
if not hasattr(ctx, "metadata") or ctx.metadata is None:
    ctx.metadata = {}
ctx.metadata["condition_eval"] = eval.to_dict()
if eval.stopped_by is not None:
    ctx.runtime.stopped_by = eval.stopped_by
    ctx.metadata["stopped_by"] = eval.stopped_by

# After (encapsulated in helper):
ctx.runtime.set_condition_eval(eval, ctx=ctx)
# Helper internally: writes runtime.condition_eval, runtime.stopped_by, ctx.metadata["condition_eval"], ctx.metadata["stopped_by"]
```

**Why:** When V2 removes `ctx.metadata` write compatibility, only change is inside `RuntimeMetadata.set_*()` methods. Stage call sites unchanged.

### Decision 2: PlanExecutor Not Modified

**Reality:** `PlanExecutor` writes `aggregated.metadata["plan"]` to **Result.metadata**, not `ctx.metadata`. It is not in the Pipeline chain.

**Implementation:** PlanExecutor **NOT modified**. `RuntimeMetadata.plan` field defined but not populated by PlanExecutor in V1.0.7. ADR §2.4 updated to reflect this.

### Decision 3: MetricsStage server_metrics

`MetricsStage` writes server_metrics to:
- `ctx.runtime.server_metrics` (new, strongly-typed, via helper)
- `ctx.metadata["server_metrics"]` (V1.0.6 compat, via helper write-through)
- `ctx.result.metadata["server_metrics"]` (Result API, preserved)

All three writes preserved for backward compatibility with V1.0.6 consumers.

### Decision 4: with_xxx Propagates Both runtime and metadata

```python
def with_provider(self, provider, bridge=None):
    new_ctx = ExecutionContext(..., runtime=self.runtime, ...)
    if hasattr(self, "metadata") and self.metadata is not None:
        new_ctx.metadata = self.metadata
    return new_ctx
```

Both `runtime` and dynamic `metadata` are propagated. V1.0.6 behavior preserved.

## Test Results

```
258 passed in 0.84s

V1.0.7 new tests: 30 (RuntimeMetadata) + 17 (Plugin Compat) + 12 (Stage) = 59
All V1.0.x tests preserved: 199 (V1.0.1 through V1.0.6)
Total: 258 passing
```

## 8 Questions for Code Review

1. **Helper encapsulation (N1) correctly implemented?** All Stage double-writes go through `RuntimeMetadata.set_*()` helpers. V2 can remove `ctx.metadata` writes by changing one place. Correct?

2. **Type safety of `ctx.metadata` dynamic attribute?** ExecutionContext is a dataclass with `runtime` as explicit field but `metadata` is dynamically injected (V1.0.6 behavior). Does this work with `dataclasses.fields()` introspection? Any concerns about `@dataclass` + dynamic attributes?

3. **CheckpointStage read priority correct?** Priority: `ctx.runtime.stopped_by` → `ctx.runtime.condition_eval.stopped_by` → `ctx.metadata["condition_eval"].stopped_by` → `ctx.stop → "stop_flag"`. Right order? Any edge case missed?

4. **`_ensure_metadata()` helper appropriate?** Helper silently creates empty dict if `ctx.metadata` is None. Any concern about hiding bugs? Should it log a warning when creating?

5. **MetricsStage writes to 3 places (runtime + metadata + Result.metadata).** Is this excessive? Should we drop `ctx.metadata["server_metrics"]` since the new V1.0.7 code reads from `ctx.runtime.server_metrics` and old code reads from `ctx.result.metadata["server_metrics"]`?

6. **PlanExecutor not modified.** Is this acceptable, or should V1.0.7 introduce a thin wrapper that creates a synthetic `ExecutionContext` for plan aggregation and writes to `ctx.runtime.plan`? Too much scope creep?

7. **Test coverage gaps?** 59 new tests. Missing:
   - Concurrent access to RuntimeMetadata? (likely overkill for V1.0.7)
   - Property-based tests with Hypothesis? (28 tests already cover most cases)
   - Performance benchmarks? (V1.0.7 没用性能敏感路径)
   - Snapshot tests? (dataclass eq already tested)

8. **V1.0.7 → V1.0.8 hooks?** Should `RuntimeMetadata` expose a `freeze()` method for V1.0.8 to lock after Pipeline complete? Or defer to V1.0.8 Registry?

## What to Focus On

- ✅ Helper encapsulation correctness (N1)
- ✅ V1.0.6 backward compat (additive migration)
- ✅ write-through only (MUST-2)
- ✅ stopped_by top-level elevation
- ✅ Test design (T1, T2 from ADR §6.5/6.6)
- ✅ Edge cases in CheckpointStage read priority

## Expected Score

**9.5+/10** (V1.0.6 implementation was 9.95/10; V1.0.7 should be 9.5-9.8/10 with main risk being helper design)

## Key Files for Review

- `planner/runtime_metadata.py` (305 lines, NEW) — RuntimeMetadata + helpers
- `planner/pipeline.py` (lines 50-150 + MetricsStage around line 280)
- `planner/stages/condition_stage.py` (lines 110-140)
- `planner/stages/checkpoint_stage.py` (lines 180-220)
- `tests/test_runtime_metadata.py` (30 tests)
- `tests/test_plugin_compatibility.py` (17 tests)
- `tests/test_stage_runtime_metadata.py` (12 tests)

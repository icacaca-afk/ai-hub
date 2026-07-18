# V1.0.8 Metadata Access API — ChatGPT Code Review Prompt

## Context

V1.0.8 ADR-0028 Metadata Access API — **implementation review** after ADR Approved 9.91/10.

**Cycle:**
- V1.0.7 RuntimeMetadata → ADR 9.85/10 + Code 9.88/10 → Accepted (682944a)
- **V1.0.8 ADR-0028 Metadata Access API → 9.91/10 ADR Approved (8070b4e)**
- **V1.0.8 Implementation (4ba05b9) → review pending**

## Files Changed (3 files, 601 insertions)

### Modified Files

1. **`planner/runtime_metadata.py`** (+156 lines)
   - 5 core getters (T1): `get_stop_reason()` / `get_metrics()` / `get_condition()` / `get_plan_progress()` / `get_custom()`
   - 5 `has_xxx()` (T2 Non-blocking adopted): `has_stop_reason()` / `has_metrics()` / `has_condition()` / `has_plan_progress()` / `has_custom()`
   - 1 resolver: `resolve_stop_reason(ctx)` (4-level priority lookup)
   - Alias: `resolve_stopped_by = resolve_stop_reason` (backward compat)
   - All V1.0.7 set_*() helpers preserved

2. **`planner/stages/checkpoint_stage.py`** (-14 lines net)
   - V1.0.7: 15-line inline priority logic for stopped_by
   - V1.0.8: 1-line `stopped_by = ctx.runtime.resolve_stop_reason(ctx)`
   - Also uses `get_metrics()` for uniform access

### New Files

3. **`tests/test_metadata_access_api.py`** (39 tests, ~430 lines)
   - TestGetStopReason (2)
   - TestGetMetrics (3) — defensive copy
   - TestGetCondition (2)
   - TestGetPlanProgress (2) — defensive copy
   - TestGetCustom (4) — returns reference (plugin semantics)
   - TestHasXxx (7) — T2 Non-blocking adopted
   - TestResolveStopReason (8) — 4-level priority
   - TestResolveStoppedByAlias (2) — backward compat
   - TestCheckpointStageUsesResolver (6) — net code reduction
   - TestBackwardCompat (4) — V1.0.7 API 100% preserved

## Key Implementation Decisions

### Decision 1: Defensive Copy for metrics/plan, Reference for custom

```python
def get_metrics(self) -> Dict[str, Any]:
    return dict(self.server_metrics)  # copy — runtime owned

def get_plan_progress(self) -> Dict[str, int]:
    return dict(self.plan)  # copy — runtime owned

def get_custom(self, name, default=None):
    return self.custom.get(name, default)  # reference — plugin namespace
```

**Why:** Runtime metadata is read-only for consumers (defensive copy). Plugin namespace is intentionally mutable (plugin needs to modify). This is "deliberate inconsistency" per ChatGPT 9.91/10.

### Decision 2: resolve_stop_reason Naming (T1 Non-blocking)

Adopted ChatGPT 9.91/10 T1: `resolve_stopped_by` → `resolve_stop_reason` for terminology consistency with `get_stop_reason()`.

Backward compat: `resolve_stopped_by = resolve_stop_reason` alias added.

### Decision 3: has_xxx() T2 Non-blocking

Adopted ChatGPT 9.91/10 T2: 5 `has_xxx()` methods for API Human Factor.

```python
if ctx.runtime.has_condition():  # vs
if ctx.runtime.get_condition() is not None:  # less readable
```

### Decision 4: CheckpointStage Net Code Reduction

V1.0.7: 15 lines inline priority logic
V1.0.8: 1 line `stopped_by = ctx.runtime.resolve_stop_reason(ctx)`
Net: -14 LOC, behavior 100% identical

### Decision 5: No new RuntimeMetadata fields

V1.0.8 only adds 11 methods to RuntimeMetadata (5 getter + 5 has_xxx + 1 resolver). Zero new fields. Zero breaking changes.

## Test Results

```
305 passed in 1.24s

V1.0.8 new tests: 39 (5 getter + 5 has_xxx + 8 resolver + 2 alias + 6 checkpoint + 4 compat + 9 others)
V1.0.7 tests: 38 (RuntimeMetadata) + 17 (Plugin Compat) + 12 (Stage) = 67
V1.0.6 + earlier: 199
Total: 305 passing
```

## 8 Questions for Code Review

1. **Getter design correct?** 5 getters + 5 has_xxx + 1 resolver. Anything missing? `get_all()` rejected (ChatGPT 9.91/10) — should we offer `to_dict()` for serialization instead (V1.0.9 LATER)?

2. **Defensive copy vs reference semantics correct?** `get_metrics()` / `get_plan_progress()` return copy. `get_custom()` returns reference. Right call? Should `get_custom()` also copy for safety?

3. **`has_metrics()` semantics correct?** `has_metrics() = bool(self.server_metrics)` — empty dict returns False. But what about `server_metrics = {"x": None}`? Should has_xxx check `not None` or `is not empty`?

4. **`resolve_stop_reason(ctx)` requires ctx?** What if ctx is None? Currently it accesses `getattr(ctx, "metadata", None)` which handles None, but the function signature is `ctx: "ExecutionContext"`. Should ctx be `Optional[ExecutionContext]`?

5. **CheckpointStage refactor correct?** 1-line resolver call. Behavior identical? Any edge case missed? Should we also extract `get_server_metrics_or_fallback(ctx)` as a helper?

6. **Alias `resolve_stopped_by` unnecessary?** V1.0.8 is first version with resolver, no external code uses `resolve_stopped_by`. Alias is for V1.0.7 code that may have inlined the priority logic. Is this correct, or should we drop the alias?

7. **V1.0.8 → V1.0.9 hooks?** Adopted ChatGPT 9.91/10 roadmap: V1.0.9 SHOULD add `runtime.is_stopped()` / `runtime.is_success()` / `runtime.stop_reason()` (more predicate methods). Should V1.0.8 add these now?

8. **Test coverage sufficient?** 39 new tests cover: getter types, defensive copy, custom reference semantics, 4-level priority, alias, CheckpointStage integration, backward compat. Missing: concurrent access? property-based tests (ChatGPT 9.91/10 Optional)?

## Expected Score

**9.5+/10** (V1.0.7 was 9.88/10, V1.0.8 is more focused; expect 9.5-9.8 range)

## Key Files for Review

- `planner/runtime_metadata.py` (lines 226-365, V1.0.8 additions)
- `planner/stages/checkpoint_stage.py` (lines 193-210, V1.0.8 refactor)
- `tests/test_metadata_access_api.py` (39 tests, NEW)
- `docs/adr/0028-metadata-access-api.md` (Accepted 9.91/10)

## Important Constraints

- ✅ **Zero new fields** (only methods added)
- ✅ **Zero breaking changes** (V1.0.7 API 100% preserved)
- ✅ **CheckpointStage behavior identical**
- ✅ **All V1.0.7 tests still pass without modification**
- ✅ **Core Freeze maintained**

# V1.0.8 ADR-0028 Metadata Access API — ChatGPT Review Prompt

## Context

V1.0.7 RuntimeMetadata (Accepted 9.88/10) introduced strongly-typed runtime metadata. V1.0.8 introduces a **Metadata Access API** to unify access patterns and reduce code duplication.

**ChatGPT 9.88/10 Q3 + Q8 explicit recommendations:**
- **Q3**: "把这套优先级 [4-级 stopped_by 查找] 抽成：RuntimeMetadata.resolve_stopped_by(ctx)。不要放在 CheckpointStage"
- **Q8 (V1.0.8 路线图)**: "MUST: Metadata Access API. MUST: Stage Registry. SHOULD: Pipeline Introspection. LATER: Schema Versioning"

This ADR covers **only Metadata Access API** (Stage Registry will be ADR-0029).

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.3 ADR-0022 + 0023 Retry/Checkpoint (9.95/10)
- V1.0.4 ADR-0024 ConditionStage (ADR 9.9/10 + Code 9.95/10)
- V1.0.5 ADR-0025 PipelineHooks (ADR 9.9/10 + Code 9.93/10)
- V1.0.6 ADR-0026 StageDescriptor (ADR 9.94/10 + Code 9.95/10)
- V1.0.7 ADR-0027 RuntimeMetadata (ADR 9.85/10 + Code 9.88/10) — Accepted
- **V1.0.8 ADR-0028 Metadata Access API (DRAFT, 98fc86f) — review pending**

## What to Review (V1.0.8 ADR-0028)

**File:** `docs/adr/0028-metadata-access-api.md` (~540 lines, Draft)

**Core Proposal:**

1. **5 core getters** (uniform access to RuntimeMetadata fields):
   ```python
   def get_stop_reason(self) -> Optional[str]
   def get_metrics(self) -> Dict[str, Any]          # returns copy
   def get_condition(self) -> Optional[ConditionEval]
   def get_plan_progress(self) -> Dict[str, int]    # returns copy
   def get_custom(self, name: str, default: Any = None) -> Any
   ```

2. **1 resolver** (encapsulates 4-level stopped_by priority):
   ```python
   def resolve_stopped_by(self, ctx: "ExecutionContext") -> Optional[str]:
       # 1. self.stopped_by  (V1.0.7 top-level)
       # 2. self.condition_eval.stopped_by  (V1.0.7 strong-typed)
       # 3. ctx.metadata["condition_eval"]["stopped_by"]  (V1.0.6 dict compat)
       # 4. ctx.stop → "stop_flag"  (fallback)
   ```

3. **CheckpointStage refactor** (~14 LOC net reduction):
   - V1.0.7: 15-line inline priority logic in `from_context`
   - V1.0.8: 1-line `stopped_by = ctx.runtime.resolve_stopped_by(ctx)`
   - Behavior identical to V1.0.7

4. **100% backward compatible** with V1.0.7:
   - All V1.0.7 property access works (`ctx.runtime.stopped_by`)
   - All V1.0.7 helpers preserved (`set_condition_eval()` etc.)
   - No new fields added to RuntimeMetadata
   - Only adds 6 methods to RuntimeMetadata class

## Key Design Decisions

1. **Getters return copies** for `get_metrics()` / `get_plan_progress()` (defensive copy)
2. **Getters don't throw** — return `None` / empty dict / default
3. **`resolve_stopped_by(ctx)`** receives ctx for metadata fallback (read-only)
4. **No new fields** — V1.0.8 field set identical to V1.0.7
5. **No `schema_version`** — adopted ChatGPT 9.85/10 Defer
6. **No `StopReason` enum** — string with namespace prefix is sufficient for V1.0.8
7. **No Stage Registry** — V1.0.8 ADR-0029 (separate)
8. **No Pipeline Introspection** — V1.0.8 ADR-0029 (separate)

## 8 Questions for Review

1. **Getter design correct?** 5 getters + 1 resolver complete? Need `get_all()` bulk accessor?

2. **Getter returns copy appropriate?** `get_metrics()` / `get_plan_progress()` return copy. `get_custom()` returns reference (allows modification). Consistent? `get_metrics()` returning reference more efficient?

3. **Resolver should receive ctx?** `resolve_stopped_by(ctx)` is required for metadata fallback. Should ctx be optional (most cases don't need dict fallback)? Or required for explicit "this is read-only"?

4. **CheckpointStage refactor net reduction sufficient?** V1.0.7 15-line priority → V1.0.8 1-line resolver call. Should also extract `get_server_metrics_or_fallback(ctx)`?

5. **Stop reason string vs enum?** V1.0.8 keeps string (e.g. `"condition:c1:skip"`, future `"retry:exhausted"`). Enum too early with V1.0.8 limited writers?

6. **No `schema_version` in V1.0.8?** Adopted ChatGPT 9.85/10 Defer (no real consumers, dead field). If V1.0.9 adds new field, V1.0.9 or V1.0.8 introduces version?

7. **No Stage Registry in this ADR?** V1.0.8 ADR-0029 covers Stage Registry (separate, scoped). Should they be combined into one V1.0.8 mega-ADR, or stay separate for incremental review?

8. **V1.0.8 完整路线图 priority**: Adopted ChatGPT 9.88/10 Q8 — MUST: Metadata Access API + Stage Registry. SHOULD: Pipeline Introspection. LATER: Schema Versioning. Should V1.0.8 contain 2 ADRs (0028 + 0029) or just 1?

## Expected Score

**9.5+/10** (V1.0.7 ADR 9.85/10, V1.0.8 is smaller and more focused; expect 9.5-9.8 range)

## Test Plan (V1.0.8)

- 15+ getter unit tests (defensive copy, return type, default values)
- 6+ resolver unit tests (priority order, edge cases)
- 3+ CheckpointStage integration tests
- 3+ backward compatibility tests
- Total: 27+ new tests, 90+ total V1.0.x

## Key Files

- **ADR:** `docs/adr/0028-metadata-access-api.md` (~540 lines, Draft, 98fc86f)
- **V1.0.7 (precedent):** `docs/adr/0027-runtime-metadata-schema.md` (Accepted)
- **V1.0.7 Code (to extend):** `planner/runtime_metadata.py` (305 lines)
- **V1.0.7 Review:** `docs/reviews/0027-code-chatgpt-review.md` (9.88/10)

## Important Constraints

- ✅ **No breaking changes** to V1.0.7
- ✅ **No new RuntimeMetadata fields**
- ✅ CheckpointStage behavior identical (only refactor)
- ✅ Third-party Stages / Hooks unaffected
- ✅ Core Freeze maintained (no `core/`, `router/`, `providers/` changes)

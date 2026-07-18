# V1.0.7 Runtime Metadata Schema — ADR Review Prompt (v2)

## Context

We are building **AI Hub** — a local AI runtime evolved from a Provider Router to an AI Operating System / Agent Runtime. The V1.0.x cycle focuses on the **ExecutionPipeline** architecture: a decorator-based, context-driven pipeline that replaces the V0.x Router subclass hierarchy.

**Strict Core Freeze:** `core/`, `router/router.py`, and `providers/` MUST NOT be modified. All extension happens in `planner/`.

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.3 ADR-0022 RetryStage + ADR-0023 CheckpointStage (9.95/10 FINAL)
- V1.0.4 ADR-0024 ConditionStage (ADR 9.9/10 + Code 9.95/10)
- V1.0.5 ADR-0025 PipelineHooks (ADR 9.9/10 + Code 9.93/10) — Accepted (34645a8)
- V1.0.6 ADR-0026 StageDescriptor (ADR 9.94/10 + Code 9.95/10) — Accepted (9b8ff1b)
- **V1.0.7 ADR-0027 Runtime Metadata Schema — v1 9.2/10 NEEDS REVISION → v2 DRAFT (dd66d8e)**

## v1 → v2 Critical Change (Adopt ChatGPT 9.2/10 Q4)

**v1 (9.2/10 NEEDS REVISION):** Breaking change — `ctx.metadata: dict → RuntimeMetadata`. You flagged this as the blocker:
- Destroys plugin API (`ctx.metadata["xxx"] = value` no longer works)
- Destroys Hook (`ctx.metadata.get(...)` no longer works)
- Makes future migration harder

**v2 (this draft, dd66d8e):** **Additive migration** — Keep `ctx.metadata: dict` 100% intact, **add** new `ctx.runtime: RuntimeMetadata` field. Built-in Stages do **double-write** (both runtime + metadata) so old code paths keep working. New code can gradually migrate to `ctx.runtime.*`.

## What to Review (V1.0.7 ADR v2)

**File:** `docs/adr/0027-runtime-metadata-schema.md` (655 lines, Draft v2)

**v2 Core Proposal:**

```python
# planner/runtime_metadata.py (NEW)
@dataclass
class RuntimeMetadata:
    server_metrics: Dict[str, Any] = field(default_factory=dict)   # V1.0.7 MUST
    condition_eval: Optional[ConditionEval] = None                  # V1.0.7 MUST
    stopped_by: Optional[str] = None                                # V1.0.7 MUST (top-level)
    plan: Dict[str, int] = field(default_factory=dict)              # V1.0.7 MUST
    custom: Dict[str, Any] = field(default_factory=dict)            # V1.0.7 MUST
    # V1.0.7 NOT: retry (V1.1), experimental (V2) — adopted your deferral advice


# planner/pipeline.py — ExecutionContext 增量
@dataclass
class ExecutionContext:
    task: Task
    provider: Optional[Provider] = None
    bridge: Any = None
    bridge_result: Optional[BridgeResult] = None
    result: Optional[Result] = None
    stop: bool = False
    # V1.0.7 新增 (adopt additive):
    runtime: RuntimeMetadata = field(default_factory=RuntimeMetadata)
    # 注: 保留旧的动态 metadata 注入 (V1.0.6 行为完全不变)
```

## v2 Key Decisions (5 critical adopts from your 9.2/10 review)

1. **Q4 Additive Migration (CRITICAL blocker resolved):**
   - 保留 `ctx.metadata: dict[str, Any]` (V1.0.6 行为 100% 不变)
   - 新增 `ctx.runtime: RuntimeMetadata` (强类型)
   - built-in Stage 双写: `ctx.runtime.condition_eval` (新) + `ctx.metadata["condition_eval"]` (旧)
   - 第三方 Stage 旧 `ctx.metadata["key"] = value` **完全不受影响**
   - 旧 Hook 读 `ctx.metadata["key"]` **完全不受影响**
   - **零 Breaking Change**

2. **Field set refinement (adopted your deferral advice):**
   - V1.0.7 MUST: `server_metrics` / `condition_eval` / `stopped_by` / `plan` / `custom`
   - V1.1: `retry` (deferred — RetryStage has no real metadata yet)
   - V2: `experimental` (deferred — "V2 真需要再加")

3. **`stopped_by` elevated (your favorite decision):**
   - From `condition_eval.stopped_by` (V1.0.4 nested) → `ctx.runtime.stopped_by` (V1.0.7 top-level)
   - Adopted: "停止原因不是 Condition 专属，未来 Retry/ManualAbort/Timeout/Cancellation/Hook 都可 stop"
   - CheckpointStage reads `ctx.runtime.stopped_by` directly (no `.get().get()` chain)

4. **No `ctx.metadata` deprecation in V1.0.7:**
   - V1.0.7: additive only (no warning, no deprecation)
   - V2: deprecated `ctx.metadata` writes (reads still work)

5. **Stage double-write strategy:**
   - All built-in Stages write to BOTH `ctx.runtime.*` (new API, strongly-typed) AND `ctx.metadata["*"]` (old API, dict)
   - CheckpointStage: prefer `ctx.runtime.stopped_by` first, fall back to `ctx.metadata["condition_eval"].stopped_by`

## Compatibility Guarantee (v2 — Zero Breaking Change)

```python
# Old code (V1.0.6 third-party Stage / Hook) — V1.0.7 100% unaffected
ctx.metadata["my_plugin_key"] = value  # ✅ 仍工作
ctx.metadata.get("condition_eval")      # ✅ 仍工作
ctx.metadata.get("condition_eval", {}).get("stopped_by")  # ✅ 仍工作

# New code (V1.0.7 built-in Stage) — recommended new API
ctx.runtime.condition_eval = ConditionEval(...)  # ✅ strongly-typed
ctx.runtime.stopped_by = "condition:abort"        # ✅ top-level
ctx.runtime.custom["my_plugin"] = value          # ✅ controlled namespace
```

## 8 Questions for v2 Review

1. **Q4 Additive Migration resolved?** v1 was 9.2/10 NEEDS REVISION due to Q4 breaking change. v2 keeps `ctx.metadata` 100% intact and adds `ctx.runtime` as new field. Does this fully resolve Q4?

2. **Field set refined per your deferral advice?** V1.0.7 = server_metrics / condition_eval / stopped_by / plan / custom. `retry` deferred to V1.1, `experimental` deferred to V2. Correct?

3. **Stage double-write necessary?** Built-in Stages write to BOTH `ctx.runtime.*` AND `ctx.metadata["*"]` so old Hooks / third-party Stages reading dict API still work. Is double-write the right migration bridge, or should we only write `ctx.runtime` and let old code paths break (forcing V1.0.7 = clean break)?

4. **`stopped_by` top-level safe?** Elevated from `condition_eval.stopped_by` to `ctx.runtime.stopped_by`. Does this break V1.0.4 Runtime Contract semantics, or is it additive (CheckpointStage falls back to nested)?

5. **No `ctx.metadata` deprecation in V1.0.7?** We keep both old and new APIs fully functional. V2 will deprecate the dict write path. Is this the right pacing, or should V1.0.7 already emit a soft warning for `ctx.metadata["reserved_key"]` writes?

6. **V1.0.8 Stage Registry interface?** Should `RuntimeMetadata` reserve a `schema_version: int = 1` field now for future evolution, or defer to V1.0.8?

7. **Test coverage sufficient?** 12 (RuntimeMetadata unit) + 5 (ExecutionContext) + 6 (Stage double-write) + 3 (compatibility) = 26 tests. Need property-based tests (Hypothesis) for arbitrary Stage combinations?

8. **V1.0.7 → V1.0.8 evolution:** You suggested Stage Registry / Metadata Access API / Schema Versioning as V1.0.8 priorities. Which is V1.0.8 MUST, which is V1.0.9? Should `RuntimeMetadata` reserve any hooks for V1.0.8 Registry (e.g. `runtime.namespace_for(stage_name)`)?

## Expected Score

**9.5+/10** (v1 was 9.2/10; v2 should resolve Q4 blocker, expecting improvement to 9.7-9.9/10 range)

## Key Files

- **ADR v2:** `docs/adr/0027-runtime-metadata-schema.md` (655 lines, Draft v2, committed dd66d8e)
- **v1 review record:** `docs/reviews/0027-adr-chatgpt-review-raw.txt` (9.2/10 NEEDS REVISION)
- **v1 draft:** commit 924f00d (preserved in git history)
- **Cycle context:** V1.0.6 ADR-0026 (9.94/10) and Code (9.95/10) all Accepted

## Bonus Context

**Important fact (now in ADR §1.1):** Current `ExecutionContext` is a non-frozen dataclass where `metadata` is **dynamically injected** via `setattr(ctx, "metadata", {})` on first write by `ConditionStage.__call__`. This means:
- `ctx.metadata` is currently NOT a dataclass field
- It's a runtime attribute added when first written
- V1.0.7 v2: `ctx.runtime` becomes a real dataclass field; `ctx.metadata` remains dynamic (V1.0.6 behavior)
- This fact makes v2 additive migration even cleaner — no field conflict, just adds a new field

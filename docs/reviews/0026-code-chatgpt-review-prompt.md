# V1.0.6 StageDescriptor — Code Review Prompt

## Context

We are building **AI Hub** — a local AI runtime evolved from a Provider Router to an AI Operating System / Agent Runtime. The V1.0.x cycle focuses on the **ExecutionPipeline** architecture: a decorator-based, context-driven pipeline that replaces the V0.x Router subclass hierarchy.

**Strict Core Freeze:** `core/`, `router/router.py`, and `providers/` MUST NOT be modified. All extension happens in `planner/`.

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.3 ADR-0022 RetryStage + ADR-0023 CheckpointStage (9.95/10 FINAL)
- V1.0.4 ADR-0024 ConditionStage (ADR 9.9/10 + Code 9.95/10)
- V1.0.5 ADR-0025 PipelineHooks (ADR 9.9/10 + Code 9.93/10) — Accepted (34645a8)
- **V1.0.6 ADR-0026 StageDescriptor (9.94/10 ADR Approved) — code under review**

## What to Review (V1.0.6 Code Implementation)

**Commit:** `d8f8c6d` — "V1.0.6: implement StageDescriptor (ADR-0026 ChatGPT 9.94/10)"

**Files (7):**

1. `planner/stage_descriptor.py` (NEW, ~140 lines) — `StageDescriptor` dataclass + `Stage` Protocol + `get_descriptor()` helper
2. `planner/pipeline.py` (MODIFIED) — `RouteStage` / `MetricsStage` get explicit descriptor + `Pipeline.run()` uses `descriptor.always_run_after_stop`
3. `planner/hooks.py` (MODIFIED) — Hook signatures accept optional `descriptor` parameter (Backwards-compat via TypeError fallback)
4. `planner/stages/retry_stage.py` (MODIFIED) — explicit descriptor
5. `planner/stages/checkpoint_stage.py` (MODIFIED) — explicit descriptor with `always_run_after_stop=True` (V1.0.4 关键)
6. `planner/stages/condition_stage.py` (MODIFIED) — explicit descriptor
7. `tests/test_stage_descriptor.py` (NEW, ~280 lines, 27 tests, 9 classes)

## ADR-0026 Approved Design (9.94/10)

### StageDescriptor (frozen dataclass)

```python
@dataclass(frozen=True)
class StageDescriptor:
    name: str                                # Required
    role: str = "stage"
    idempotent: bool = True
    has_side_effects: bool = False
    always_run_after_stop: bool = False      # V1.0.4 Checkpoint key
    version: int = 1
    description: str = ""
    owner: str = "ai-hub"
    experimental: bool = False
    capabilities: FrozenSet[str] = field(default_factory=frozenset)
```

### Stage Protocol (Q4 ChatGPT 采纳: Protocol 替代基类)

```python
@runtime_checkable
class Stage(Protocol):
    descriptor: StageDescriptor
    def __call__(self, ctx: ExecutionContext) -> ExecutionContext: ...
```

### get_descriptor() (Q7 Critical: 兼容性 helper)

```python
def get_descriptor(stage) -> StageDescriptor:
    if hasattr(stage, "descriptor") and isinstance(stage.descriptor, StageDescriptor):
        return stage.descriptor
    name = getattr(stage, "name", "stage")
    return StageDescriptor(name=name)  # 永远 always_run_after_stop=False
```

**Key Invariant (Q7 Critical):**
- ✅ All built-in Stages (Route / Metrics / Retry / Checkpoint / Condition) have **explicit descriptor** (no `hasattr(stage, "store")` duck typing)
- ✅ Default descriptor fallback `always_run_after_stop=False` (never infers checkpoint semantics)
- ✅ `CheckpointStage.descriptor.always_run_after_stop = True` (V1.0.4 ChatGPT 9.95/10 采纳: Checkpoint 总是写, 即使 abort)

### Pipeline.run() V1.0.6 Refactor

**Before (V1.0.5):** String + duck typing
```python
if stage.name == "checkpoint" and hasattr(stage, "store"):
    ctx = stage(ctx)
```

**After (V1.0.6):** Single behavior signal
```python
descriptor = get_descriptor(stage)
if descriptor.always_run_after_stop:
    ctx = stage(ctx)
```

### Hook Signature Extension (Backwards-Compatible)

```python
def fire_before_stage(ctx, stage_name, descriptor=None):
    for hook in self.before_stage:
        try:
            try:
                hook(ctx, stage_name, descriptor=descriptor)
            except TypeError:
                # V1.0.5 旧 Hook 不接受 descriptor 参数
                hook(ctx, stage_name)
        except Exception as e:
            logger.warning(...)
```

- ✅ V1.0.5 Hooks (接受 `(ctx, stage_name)`) 仍可工作
- ✅ V1.0.6 新 Hooks (接受 `(ctx, stage_name, descriptor)`) 可用 descriptor 做决策

### Tests (27 passing, 9 classes)

- `TestStageDescriptorDefaults` (3)
- `TestStageDescriptorFrozen` (4) — Q8 采纳
- `TestStageDescriptorHashable` (3)
- `TestStageDescriptorCapabilities` (2)
- `TestStageDescriptorBehavioralFlags` (3)
- `TestStageProtocol` (3) — Q4 采纳
- `TestGetDescriptor` (5) — Q7 + Q8 采纳
- `TestStageDescriptorExperimental` (2)
- `TestStageDescriptorVersion` (2)

**V1.0.x Test Suite:** 179 tests passing (152 + 27 new)

## Specific Questions

1. **StageDescriptor dataclass shape:** Is `name` (only required) + 10 optional fields the right structure? Or should some be grouped (e.g. `Metadata` sub-dataclass)?

2. **`FrozenSet[str]` for capabilities:** Better than `Set[str]` for hashability but slightly less ergonomic. Is this a worthwhile trade-off, or should we accept `Set[str]` and provide a `to_frozen()` method?

3. **Protocol vs ABC:** Q4 adopted Protocol. Is `@runtime_checkable` enough, or should V1.0.6 also add explicit `is_stage(x)` helper for clearer type narrowing?

4. **Lazy import in pipeline.py:** The descriptor instantiation uses lazy import (`from planner.stage_descriptor import StageDescriptor as _SD`) to avoid circular dependency with stage_descriptor.py importing `ExecutionContext`. Is this acceptable, or should stage_descriptor.py define Protocol without importing ExecutionContext (using `TYPE_CHECKING`)?

5. **Hook `TypeError` fallback pattern:** Smart-calling old vs new Hook signatures via `try/except TypeError` is pragmatic but feels fragile. Should we instead require V1.0.6 users to migrate Hooks, or document this as a stable compatibility shim?

6. **`always_run_after_stop` as only signal:** Q2 adopted "Behavior > taxonomy" — single signal. But is this sufficient? What if a future V2 Stage needs to also bypass stop for capability routing?

7. **Built-in Stage migration completeness:** I added `descriptor` to all 5 built-in Stages. Are there any other places in `planner/` that do `stage.name == "..."` or `hasattr(stage, "...")` that I missed?

8. **V1.0.4 backward compat preserved?** The 5 `TestCheckpointStageV104Aborted` tests must still pass. They test that `CheckpointStage` writes even on `ctx.stop=True`. Does the V1.0.6 refactor preserve this?

9. **Test coverage:** 27 tests cover constructor, frozen, hash, equality, capabilities, behavioral flags, Protocol, get_descriptor, experimental, version. Any gaps?

10. **V1.0.7 Runtime Metadata Schema (ADR-0027) preparation:** Does V1.0.6 introduce any namespace conflicts that would block ADR-0027? (e.g. `ctx.metadata` keys vs `descriptor` fields?)

## Scoring Rubric

- 9.0+ = Production-quality, ship as-is
- 9.5+ = Minor polish suggestions (non-blocking)
- 9.9+ = Exceptional, with optional roadmap hints

## Deliverables

Please return:
1. **Score** (0-10) with rationale
2. **Adopt-or-defer table** for each suggestion (Critical / Non-blocking / Defer)
3. **Recommended adjustments** (concrete, code-level)
4. **V1.0.7 ADR-0027 hints** (Runtime Metadata Schema, Stage Registry)

Thank you!

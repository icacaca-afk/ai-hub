# V1.0.7 Runtime Metadata Schema — ADR Review Prompt

## Context

We are building **AI Hub** — a local AI runtime evolved from a Provider Router to an AI Operating System / Agent Runtime. The V1.0.x cycle focuses on the **ExecutionPipeline** architecture: a decorator-based, context-driven pipeline that replaces the V0.x Router subclass hierarchy.

**Strict Core Freeze:** `core/`, `router/router.py`, and `providers/` MUST NOT be modified. All extension happens in `planner/`.

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.3 ADR-0022 RetryStage + ADR-0023 CheckpointStage (9.95/10 FINAL)
- V1.0.4 ADR-0024 ConditionStage (ADR 9.9/10 + Code 9.95/10)
- V1.0.5 ADR-0025 PipelineHooks (ADR 9.9/10 + Code 9.93/10) — Accepted (34645a8)
- V1.0.6 ADR-0026 StageDescriptor (ADR 9.94/10 + Code 9.95/10) — Accepted (9b8ff1b)
- **V1.0.7 ADR-0027 Runtime Metadata Schema — DRAFT (924f00d), under review**

## What to Review (V1.0.7 ADR)

**File:** `docs/adr/0027-runtime-metadata-schema.md` (496 lines)

**Core Proposal:**

Introduce `RuntimeMetadata` — a strongly-typed dataclass container that replaces `ctx.metadata: dict[str, Any]`. This eliminates string-based key conventions and unifies V1.0.x scattered metadata usage.

```python
@dataclass
class RuntimeMetadata:
    server_metrics: Dict[str, Any] = field(default_factory=dict)  # V1.0.1
    condition_eval: Optional[ConditionEval] = None                  # V1.0.4
    stopped_by: Optional[str] = None                                # V1.0.7 elevated
    plan: Dict[str, int] = field(default_factory=dict)              # V1.0.7
    retry: Dict[str, Any] = field(default_factory=dict)             # V1.0.7 reserved (V1.1)
    custom: Dict[str, Any] = field(default_factory=dict)            # user plugin namespace
    experimental: Dict[str, Any] = field(default_factory=dict)      # V1.0.7 reserved
```

**Key Decisions:**

1. **Strong typing** — `ctx.metadata.condition_eval` (attribute) replaces `ctx.metadata["condition_eval"]` (string key).

2. **V1.x reserved keys** — All built-in keys (server_metrics / condition_eval / stopped_by / plan / retry / custom / experimental) documented in Runtime Contract §10.

3. **`stopped_by` elevated** — From `condition_eval.stopped_by` (V1.0.4) to top-level `stopped_by` (V1.0.7). This is the key field that `CheckpointStage` reads.

4. **Breaking change** — `ctx.metadata: dict → RuntimeMetadata`. All built-in Stages updated. User plugins migrate to `ctx.metadata.custom.*` namespace.

5. **`custom` namespace** — User plugins write `ctx.metadata.custom["my_key"] = ...` (controlled).

6. **`experimental` field** — Reserved for V2 use, V1.x doesn't consume it.

## Motivation (Why Now?)

From V1.0.6 ChatGPT 9.95/10 review:
> "下一步不要继续增加新的 Stage, 而应开始稳定运行时元数据模型。"
> "Runtime Metadata Schema: 统一 ctx.metadata 的命名空间和字段约定, 避免后续 Stage 各自定义键名。"

### Current Pain Points

**1. Naming collision risk:** Any Stage can write `ctx.metadata["any_key"]` — no namespace isolation.

**2. Implicit cross-stage coupling:**
```python
# CheckpointStage depends on ConditionStage writing "condition_eval" string key
class CheckpointStage:
    def _extract_stopped_by(self, ctx):
        return ctx.metadata.get("condition_eval", {}).get("stopped_by") or "stop_flag"
```

**3. Lack of documentation:** Runtime Contract only says `ctx.metadata: dict[str, Any]`, no V1.x reserved keys list.

## Specific Questions

1. **RuntimeMetadata field set:** `server_metrics / condition_eval / stopped_by / plan / retry / custom / experimental` — right set? Which V1.0.7 MUST, which V2?

2. **dataclass vs TypedDict vs Pydantic:** V1.0.7 uses dataclass. Is this correct? V2 upgrade to Pydantic?

3. **`stopped_by` elevated to top-level:** V1.0.4 ChatGPT adopted but didn't elevate. Should V1.0.7 elevate? Will this break V1.0.4 Runtime Contract?

4. **Breaking change handling:** `ctx.metadata: dict → RuntimeMetadata` is breaking. Should V1.0.7 fully switch, or dual-API (`ctx.metadata` still dict, new `ctx.runtime` strong-typed)?

5. **`custom` namespace:** User plugin controlled namespace — too strict? Or allow fully free (V1.x risk)?

6. **`experimental` field:** V1.x doesn't use — is reservation worth it? Or skip and add in V2?

7. **`retry` field reserved in V1.0.7 but V1.1 enables:** Is adding an empty `field` in V1.0.7 premature? Or V2 add?

8. **V1.0.x compatibility:** User plugin old `ctx.metadata["key"]` syntax — emit warning (deprecation) or hard fail (breaking)?

9. **Test coverage:** 10 + 5 + 3 tests sufficient? Need property-based (Hypothesis)?

10. **V1.0.8 Stage Registry preparation:** Does RuntimeMetadata give Registry a good interface? E.g. `descriptor.metadata_field = "condition_eval"`?

## Scoring Rubric

- 9.0+ = Production-quality, ship as-is
- 9.5+ = Minor polish suggestions (non-blocking)
- 9.9+ = Exceptional, with optional roadmap hints

## Deliverables

Please return:
1. **Score** (0-10) with rationale
2. **Adopt-or-defer table** for each suggestion (Critical / Non-blocking / Defer)
3. **Recommended adjustments** (concrete, code-level)
4. **V1.0.8+ roadmap hints** (Stage Registry / V2 Pydantic migration)
5. **Critical issue analysis** — especially around Q4 (Breaking change) and Q3 (stopped_by elevation)

Thank you!

# V1.0.6 StageDescriptor — ChatGPT ADR Review (9.94/10 APPROVED)

**Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**ADR Reviewed:** `docs/adr/0026-stage-descriptor.md` (commit a535b3c)
**Verdict:** **APPROVED with one Critical migration requirement**

---

## 1. Score

**9.94 / 10**

> "This ADR is the natural continuation of ADR-0021 through ADR-0025. It removes the last significant piece of string-based coupling (`stage.name == "checkpoint"`) and replaces it with explicit metadata. That's exactly the kind of evolution expected in a runtime architecture."

> "The only issue I consider blocking is the compatibility question around CheckpointStage (your Q7). Everything else is polish or roadmap material."

## 2. Sub-Scores

| Area | Score | Notes |
|------|-------|-------|
| Architecture | 10/10 | Clear separation of behavior vs metadata |
| Pipeline decoupling | 10/10 | Removes duck typing cleanly |
| Runtime evolution | 10/10 | Strong foundation for Stage Registry |
| API stability | 9.8/10 | Hook signature extension is acceptable |
| Compatibility | 9.4/10 | One migration rule required |
| Future extensibility | 10/10 | Descriptor enables many V2 features |

**Final: 9.94 / 10**

## 3. Q&A Response

### Q1: Field Set → 建议分层

**V1.0.6 Core (直接驱动 Runtime 行为):**
- `name` / `role` / `idempotent` / `has_side_effects` / `always_run_after_stop`

**V1.x Metadata (informational):**
- `description` / `version` / `experimental` / `owner`

**V2 (Capabilities):**
- `capabilities` 保留在 dataclass 但 Runtime Contract 不要依赖（V2 Stage Registry / Plugin / UI 消费）

**优先级：** Adopt。

### Q2: Pipeline Decoupling → 充分

> "I would not also check `descriptor.role == "checkpoint"` because that creates two sources of truth. The runtime should care about behavior, not semantic category. **Behavior > taxonomy.**"

**优先级：** Adopt。`always_run_after_stop` 单一信号，不再加 role 二次检查。

### Q3: Hook Signature → 接受

> "Optional typed parameters are preferable to **kwargs."

**优先级：** Adopt。

### Q4: Base Class vs Protocol → **改为 Protocol** ⭐

> "Current architecture has intentionally avoided inheritance. RetryStage / MetricsStage / CheckpointStage / ConditionStage already follow structural typing. A Protocol preserves that philosophy. A concrete base class starts nudging users toward inheritance. **Use Protocol.**"

**优先级：** 非阻塞，Adopt。**重要改动：移除 `class Stage` 基类，改用 `Protocol`。**

### Q5: Role String vs Enum → 保持字符串

> "Don't introduce Enum in V1. Runtime never switches on role. It's documentation metadata. Enum becomes worthwhile once Stage Registry / UI / Plugin loading begin consuming it."

**优先级：** Adopt。V1.0.6 字符串，V2 转 Enum。

### Q6: Set vs List → Set

> "Capabilities are semantic labels. Duplicate labels have no meaning. **Set[str] is correct.**"

**优先级：** Adopt。

### Q7: Compatibility → **Critical 调整** ⭐

> "Current compatibility factory `StageDescriptor(name=stage.name)` would indeed lose `always_run_after_stop=True` for CheckpointStage. That would silently break V1.0.4 semantics. This is not acceptable."

**Option A (推荐):** Require every built-in Stage to declare `descriptor = ...` explicitly. This is clean, no heuristics.

**Option B (Reject):** Factory detects `hasattr(stage, "store")` — that recreates duck typing, exactly what ADR-0026 removes. **Reject.**

**Option C (推荐采纳):** Migration requirement. ADR should explicitly state: "All built-in stages introduced before ADR-0026 MUST define an explicit descriptor during migration." Then compatibility factory exists only for user plugins / legacy extensions.

**优先级：** **Critical**, Adopt.

### Q8: Tests → 加 2 个

- **Immutable descriptor test:** `descriptor.role = ...` should fail.
- **Legacy fallback test:** Stage without `descriptor` receives default descriptor.
- Property testing is unnecessary.

**优先级：** 非阻塞，Adopt。

### Q9: Runtime Contract → 保持 ADR 内

> "I wouldn't split `stage-descriptor.md` yet. The descriptor is still tightly coupled to pipeline execution. Keep it in ADR-0026. Later when Registry / Plugins / UI appear, then extract."

**优先级：** Adopt。

### Q10: Runtime Metadata Schema → **独立 ADR-0027** ⭐

> "StageDescriptor answers: **What is a Stage?** Metadata answers: **What happened during execution?** Different concepts. Don't mix them."

**优先级：** Adopt，独立 ADR-0027。

## 4. Adopt / Defer Summary

| 建议 | 优先级 | 状态 |
|------|--------|------|
| **所有 built-in Stage 显式定义 descriptor** | **Critical** | **采纳 (本 commit)** |
| 改 `Stage` 基类为 `Protocol` | 非阻塞 | **采纳 (本 commit)** |
| `always_run_after_stop` 单一行为信号 | Adopt | 当前设计正确 |
| `role` 保持字符串 | Adopt | V1.0.6 字符串 |
| `capabilities` Set[str] | Adopt | 当前设计正确 |
| Hook 签名加 `descriptor` 可选参数 | Adopt | 当前设计正确 |
| 加 immutable descriptor 测试 | 非阻塞 | **采纳 (本 commit)** |
| 加 legacy fallback descriptor 测试 | 非阻塞 | **采纳 (本 commit)** |
| Stage Registry | Defer | V2 |
| Role Enum | Defer | V2 |
| Runtime Metadata Schema | Defer | **ADR-0027** |

## 5. Code-Level Adjustments (本 commit 采纳)

### 5.1 移除 `Stage` 基类，改用 `Protocol`

```python
# V1.0.6 改:
from typing import Protocol, runtime_checkable

@runtime_checkable
class Stage(Protocol):
    """Stage 接口约定 (Protocol, 非继承要求)."""
    descriptor: StageDescriptor

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext: ...
```

### 5.2 所有 built-in Stage 显式 descriptor

```python
class CheckpointStage:
    descriptor = StageDescriptor(
        name="checkpoint",
        version=1,
        role="checkpoint",
        capabilities={"persists_state"},
        idempotent=True,
        has_side_effects=True,
        always_run_after_stop=True,  # V1.0.4 关键
        description="Persists execution snapshot to ExecutionStore",
    )
```

### 5.3 兼容性 helper（仅给 user plugin / legacy）

```python
def get_descriptor(stage) -> StageDescriptor:
    """V1.0.6: 提取 Stage Descriptor, 兼容 V1.0.x 旧 Stage.
    
    关键: built-in Stage 全部显式 descriptor, 此 helper 仅给:
      - user plugin
      - legacy extension
    绝不推断 checkpoint 语义 (不再 hasattr(stage, "store") 探测).
    """
    if hasattr(stage, "descriptor") and isinstance(stage.descriptor, StageDescriptor):
        return stage.descriptor
    name = getattr(stage, "name", "stage")
    return StageDescriptor(name=name)
```

## 6. V1.0.7 Roadmap (ChatGPT 建议)

> "This ADR creates a very strong foundation. I would now avoid adding more Stage types and instead consolidate runtime metadata and stage management."

1. **Stage Registry** — 集中注册和查找 StageDescriptors
2. **Runtime Metadata Schema (ADR-0027)** — 定义 `ctx.metadata` 结构 (condition_eval / server_metrics / stopped_by / future tracing)
3. **Descriptor Validation** — 启动时校验 descriptor 唯一性 / 保留 role / 不兼容 flag 组合

## 7. 总体结论

> **Score: 9.94 / 10**
> **Verdict: APPROVED (with one compatibility requirement)**
>
> The clean solution is not to make the compatibility layer smarter through heuristics. Instead, make the migration explicit: every built-in stage defines its own descriptor. The compatibility factory is reserved exclusively for legacy or third-party stages.
>
> This preserves V1.0.x behavior, removes string-based coupling, and keeps the architecture internally consistent. This is the one adjustment I'd require before considering ADR-0026 complete.

## 8. V1.0.6 ADR 状态

**本 commit (V1.0.6 ADR Accepted) 采纳：**

**Critical 调整 (Q7):**
- ✅ 所有 5 个 built-in Stage (Route/Metrics/Retry/Checkpoint/Condition) 显式定义 `descriptor`
- ✅ 兼容性 helper 仅给 user plugin / legacy，绝不推断 checkpoint 语义

**非阻塞 调整 (Q4 + Q8):**
- ✅ `Stage` 基类 → `Protocol` (runtime_checkable)
- ✅ 加 immutable descriptor 测试
- ✅ 加 legacy fallback descriptor 测试

**保持不变：**
- ✅ `always_run_after_stop` 单一行为信号
- ✅ `role` 字符串（V2 转 Enum）
- ✅ `capabilities` Set[str]
- ✅ Hook 签名加 `descriptor` 可选参数
- ✅ Runtime Contract 同步在 ADR-0026 内

**V1.0.7 独立 ADR-0027：** Runtime Metadata Schema 统一（条件评估 / server metrics / stopped_by / future tracing）

**V2 路线：** Stage Registry / Role Enum / Descriptor Validation

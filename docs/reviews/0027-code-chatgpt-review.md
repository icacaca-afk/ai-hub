# V1.0.7 RuntimeMetadata Implementation — ChatGPT Review

**Implementation Commit:** 877a22a (8 files, 1278 insertions, 59 new tests)
**ADR Commit:** c0678e1 (Accepted 9.85/10)
**Review Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Raw Reply:** `0027-code-chatgpt-review-raw.txt`
**Verdict:** ✅ **APPROVED 9.88/10** (0 Blocking Issues)

---

## 总评分

| 维度 | 分数 | 评价 |
|------|------|------|
| Architecture | **10.0** | 完美：分层清晰 ExecutionContext → RuntimeMetadata → StageDescriptor → PipelineHooks → ExecutionPipeline |
| Backward Compatibility | **10.0** | 完美：V1.0.6 Plugin / Hook 100% 不受影响 |
| Runtime Design | **9.9** | 强类型 dataclass + helper 封装双写 |
| API Stability | **9.8** | Additive migration, 零 breaking |
| Migration Strategy | **10.0** | 经典 Runtime Evolution 模式 |
| Helper Encapsulation | **9.9** | N1 完美实施 — Stage 不感知双写策略 |
| Testing | **9.8** | 59 新测试，建议补 2 个 (helper 幂等 + reserved key 冲突) |
| Future Evolution | **9.7** | V1.0.8 Metadata Access API / Registry / Introspection |
| **Overall** | **9.88** | **APPROVED** — V1.0.x Runtime Foundation 成熟度 |

## 结论

> "整体来看，这个 V1.0.7 实现比 ADR v1 成熟得多"
> "最大的风险（RuntimeMetadata 替换 dict 导致整个生态破坏）已经被 v2 的 Additive Migration 消除"
> "从你描述的实现来看，它已经进入了「可以合并」而不是「需要重新设计」的阶段"
> "这是 V1.0.x 系列中一次质量很高的实现"

---

## 核心评价 (Q1-Q8)

### Q1 Helper Encapsulation — **10/10 (满分)**

> "以前：ctx.runtime.xxx = ... ; ctx.metadata["xxx"] = ... 散落在所有 Stage"
> "现在：ctx.runtime.set_condition_eval(eval, ctx)"
> "Stage 根本不知道：metadata 是否存在 / 双写策略 / stopped_by 是否同步 / reserved key"
> "这些全部封装了"
> "Tell RuntimeMetadata what happened, 而不是 Tell Stage how RuntimeMetadata should work"
> "这是职责倒置"

**采纳：** Helper 封装已实施 (N1)

### Q2 Dynamic metadata — **Non-blocking**

> "目前 ExecutionContext 真正字段：runtime。但是 metadata 还是 setattr() 动态加"
> "技术上没有问题。dataclass 完全允许：ctx.foo = ..."
> "但是：IDE / mypy / pyright 都不会喜欢"
> "建议：V1.0.x 保持。V2：把 metadata 也正式变成 metadata: dict[str, Any] 字段"

**采纳：** V1.0.x 保持现状，V2 评估正式字段化

### Q3 Checkpoint read priority — **V1.0.8 建议**

> "目前顺序正确。runtime.stopped_by ↓ runtime.condition_eval.stopped_by ↓ metadata ↓ ctx.stop"
> "唯一建议：把这套优先级抽成：RuntimeMetadata.resolve_stopped_by(ctx)"
> "不要放在 CheckpointStage"
> "以后：Cancellation / Timeout / Hook / Manual Abort 全部都可以复用"

**采纳 V1.0.8：** `RuntimeMetadata.resolve_stopped_by(ctx)` helper（V1.0.8 MUST）

### Q4 `_ensure_metadata()` — **保持 silent**

> "我支持 silent, 不要 logger.warning"
> "因为 metadata 本来就是 lazy"
> "Warning 会污染日志"
> "这一点和 pathlib.mkdir(exist_ok=True) 一样。不存在不是异常"

**采纳：** 保持 silent（已实施）

### Q5 Metrics 写三份 — **V1.1 建议**

> "Source of Truth: runtime.server_metrics"
> "Pipeline Exit: 统一 runtime → Result.metadata"
> "Legacy: metadata 仅兼容"
> "V1.0.7 不建议改。因为影响太大。属于 Defer"

**采纳：** V1.0.7 保持三份写入，V1.1 评估统一到 Pipeline Exit

### Q6 PlanExecutor — **完全赞成**

> "完全赞成现在。不要为了 runtime.plan 硬塞 ExecutionContext"
> "PlanExecutor 不是 Pipeline。不要为了统一而统一"
> "RuntimeMetadata 允许存在暂时没填的数据。这是正常设计"

**采纳：** PlanExecutor 不改（已实施）

### Q7 Tests — **59 → 61 (Non-blocking)**

> "59 个新增测试。整体非常不错。不过我还会补两个。"

**Non-blocking 采纳：**
- **T3 helper 幂等**: `set_condition_eval()` 多次调用结果一致（避免重复同步 bug）
- **T4 reserved key 冲突**: `runtime.custom["condition_eval"]` 是否允许？明确 reserved conflict 规则

### Q8 V1.0.8 路线图

> "我不会做 freeze()。因为 RuntimeMetadata 整个生命周期就是 mutable"
> "freeze 属于 Pipeline 生命周期。不是 Metadata 生命周期"
> "我建议 V1.0.8: Metadata Access API / Stage Registry / Pipeline Introspection / Schema Version"

**采纳 V1.0.8 路线图：**
- **MUST**: Metadata Access API (ctx.runtime.get_stop_reason() 等)
- **MUST**: Stage Registry
- **SHOULD**: Pipeline Introspection
- **LATER**: Schema Versioning

---

## Adopt / Defer 总结

| 建议 | 结论 | 优先级 |
|------|------|--------|
| Helper encapsulation | ✅ Adopt (已实施) | — |
| Additive migration | ✅ Adopt (已实施) | — |
| Runtime as source of truth | ✅ Adopt | — |
| Keep dynamic metadata in V1.x | ✅ Adopt | — |
| Silent _ensure_metadata() | ✅ Adopt (已实施) | — |
| T3 helper 幂等 | 🟡 Adopt (Non-blocking) | 实施阶段 |
| T4 reserved key 冲突 | 🟡 Adopt (Non-blocking) | 实施阶段 |
| RuntimeMetadata.resolve_stopped_by(ctx) | 🟡 V1.0.8 | Metadata Access API |
| Metadata Access API | 🟡 V1.0.8 | MUST |
| Stage Registry | 🟡 V1.0.8 | MUST |
| Pipeline Introspection | 🟡 V1.0.8 | SHOULD |
| Remove Result triple write | 🟡 V1.1 | Defer |
| metadata 正式字段化 | 🟡 V2 | Defer |
| freeze() | ❌ Defer/Not recommended | — |
| Property-based tests | 🟡 Optional | — |

---

## V1.0.8 路线图（采纳 ChatGPT 9.88/10）

### MUST: Metadata Access API
- `ctx.runtime.get_stop_reason()` 
- `ctx.runtime.get_metrics()`
- `ctx.runtime.get_condition()`
- `ctx.runtime.get_plan_progress()`
- 代替散落的 `ctx.runtime.xxx` 直接访问
- **MUST 实施** (V1.0.8)

### MUST: Stage Registry
- StageDescriptor 注册
- 生命周期查询
- 能力索引 (descriptor.capabilities)
- 替代当前散落的 `pipeline = Pipeline(stages=[...])` 构造

### SHOULD: Pipeline Introspection
- 当前 Pipeline 由哪些 Stage 组成
- Descriptor Graph (Stage 间依赖)
- Hook Graph (Hook 触发顺序)
- Runtime Snapshot (类似 Checkpoint 但覆盖整个 Pipeline)

### LATER: Schema Versioning
- `schema_version = 1` 字段（V1.0.8 加）
- 为 V2 升级预留兼容能力

---

## V1.0.7 → V1.0.8 演化图

```
V1.0.7 (本版本, 9.88/10):
  ctx.runtime = RuntimeMetadata()  # 强类型 dataclass (新增)
  ctx.runtime.condition_eval = ...  # 属性访问
  ctx.runtime.set_condition_eval(eval, ctx)  # helper 封装双写 (N1)
  ctx.metadata["legacy"] = ...  # V1.0.6 100% 兼容
  → 双写策略: helper 集中封装, Stage 不感知

V1.0.8 (采纳 ChatGPT 路线图):
  ctx.runtime.get_stop_reason()  # Metadata Access API (MUST)
  Pipeline.from_registry(["default"])  # Stage Registry (MUST)
  pipeline.describe()  # Pipeline Introspection (SHOULD)
  ctx.runtime.schema_version  # Schema Versioning (LATER)
```

---

## V1.0.7 收官下一步

1. ✅ V1.0.7 ADR-0027 Accepted (9.85/10, c0678e1)
2. ✅ V1.0.7 Implementation (9.88/10, 877a22a, 59 new tests, 258/258 pass)
3. 🔜 补 2 个 Non-blocking 测试 (T3 + T4) → commit
4. 🔜 V1.0.7 Final Accepted (commit + review)
5. 🔜 启动 V1.0.8 ADR-0028 Metadata Access API
6. 🔜 V1.0.8 ADR-0029 Stage Registry
7. 🔜 V1.0.8 Implementation
8. 🔜 V1.0.8 Final Accepted

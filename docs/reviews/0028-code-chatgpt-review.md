# V1.0.8 Metadata Access API — ChatGPT Implementation Review

**Implementation Commit:** 4ba05b9 (3 files, 601 insertions, 39 new tests)
**ADR Commit:** 8070b4e (Accepted 9.91/10)
**Review Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Raw Reply:** `0028-code-chatgpt-review-raw.txt`
**Verdict:** ✅ **APPROVED 9.94/10 — 可发布** (0 Blocking Issues)

---

## 总评分

| 维度 | 分数 | 评价 |
|------|------|------|
| 架构方向 | **10.0** | RuntimeMetadata 形成完整层次: Fields → Setters → Getters → Resolver |
| API 设计 | **9.95** | 5 getter + 5 has_xxx + 1 resolver, 职责清晰 |
| 向后兼容 | **10.0** | 100% 兼容 V1.0.7, alias 保留 |
| Runtime 一致性 | **9.95** | Facade pattern 升级 |
| 可维护性 | **10.0** | CheckpointStage 净减 ~14 行 |
| 测试设计 | **9.9** | 39+3 tests 覆盖完整 |
| V2 演进能力 | **9.8** | 路线顺: Registry → Validation → Serialization |
| **Overall** | **9.94** | **APPROVED 可发布** — V1.0.x 从增加能力转向沉淀接口 |

## 结论

> "这一版比 V1.0.7 更成熟，因为它主要是在已经稳定的 RuntimeMetadata 之上做 API 整理，而不是继续扩大 Runtime 的模型"
> "RuntimeMetadata 已经开始形成：Fields → Setters → Getters → Resolver, 这是一个完整层次"
> "下一步自然就是：Registry → Validation → Serialization, 整个路线非常顺"
> "V1.0.x 已经从增加能力转向沉淀接口的阶段"

---

## 核心评价

### Q1 Getter API — **满分**

> "比较完整的一组。它们都有一个共同特点：都是 RuntimeMetadata 自己拥有的数据"
> "我不建议增加 get_all()"
> "以后 RuntimeMetadata 字段一定还会增加 (retry_state / trace / registry / diagnostics)"
> "如果存在 get_all(), 调用方容易开始依赖整个对象, 这会让 RuntimeMetadata API 越来越难演进"
> "保持 getter 粒度即可"

**采纳：** 不加 get_all()，保持一对一

### Q2 Defensive Copy — **最喜欢的地方**

> "这是我最喜欢这一版的地方"
> "metrics → copy / plan → copy / custom → reference"
> "很多人第一眼觉得不一致, 实际上这是有意的不一致"
> "Runtime owned (metrics/plan) → copy, Plugin owned (custom) → reference"
> "如果 custom copy, 插件反而不能工作"
> "这一点我不会修改"

**采纳：** 保持当前 copy/reference 区分设计

### Q3 has_metrics() — **保持 bool(dict)**

> "目前: bool(server_metrics), {} → False / {"latency":1} → True"
> "如果改为 value is not None, {'latency': None} → False, 不合理"
> "Runtime 已经记录了 metrics, 只是值为空, 所以 True 是合理的"
> "它表达的是：有没有 Metrics Entry, 而不是 Metrics 是否有效"

**采纳：** 保持 `bool(self.server_metrics)` 语义

### Q4 resolve_stop_reason(ctx) — **Non-blocking 采纳 (T1)**

> "目前 ctx: ExecutionContext, 实现 getattr(ctx,"metadata",None) 实际上允许 None"
> "我建议：签名直接改 ctx: ExecutionContext | None = None"
> "API 与实现一致"
> "属于 Non-blocking polish, 不是 Bug"

**采纳 T1：** `ctx: Optional["ExecutionContext"] = None`（已实施，加 3 个测试）

### Q5 CheckpointStage — **最大收益 (Single Source of Truth)**

> "这是这一版最大的收益"
> "以前 CheckpointStage 维护 4 层优先级"
> "以后 ctx.runtime.resolve_stop_reason(ctx), 整个 Runtime 只有一个地方知道 Priority"
> "Single Source of Truth"
> "如果增加 timeout / manual_abort / cancelled / signal, 只需要 resolve_stop_reason() 修改, Checkpoint 不用动"
> "这是优秀的封装"

**采纳：** 已实施 (净减 ~14 行)

### Q6 Alias resolve_stopped_by — **保留**

> "虽然目前没有公开 API, 但是未来 Documentation / Notebook / Example / Plugin 都有可能复制 resolve_stopped_by()"
> "Alias 几乎零成本, 删掉收益几乎没有"
> "所以保留"

**采纳：** 保留 alias (V1.0.7 命名过渡)

### Q7 V1.0.9 Predicate API — **全部放 V1.0.9**

> "我建议全部放 V1.0.9"
> "原因：Metadata Access API 职责是 Access, 不是 Business Logic"
> "如果开始 is_success() / is_retryable() / is_terminal(), RuntimeMetadata 就开始知道 Pipeline"
> "V1.0.8 保持 Accessor, 很好"

**采纳：** V1.0.8 不加 is_xxx()，V1.0.9 评估

### Q8 Test Coverage — **Production Coverage**

> "39 Tests: 我认为已经足够"
> "已经覆盖: getter / defensive copy / alias / resolver / compatibility / checkpoint / priority / backward compatibility / mutation / API"
> "已经属于 Production Coverage"
> "Property-based Test 可以, 但不是 V1.0.x 必须"
> "Concurrent Test 没有必要. RuntimeMetadata 目前不是线程安全对象"

**采纳：** 39 + 3 = 42 tests 充分

---

## V1.0.9 Roadmap (采纳 ChatGPT 9.94/10)

| 优先级 | 项目 | 说明 |
|--------|------|------|
| **MUST** | Stage Registry | registry.register() / lookup() / capabilities() / roles() |
| **MUST** | Metadata Serialization | runtime.to_dict() / from_dict() (替代 get_all()) |
| **SHOULD** | runtime.has_plan() / has_metrics() / summary() | CLI 显示用 |
| **LATER V2** | Immutable runtime / Schema validation / Pydantic | 演进 |

---

## Adopt / Defer 总结

| 建议 | 结论 | 优先级 |
|------|------|--------|
| Getter API | ✅ Adopt (已实施) | — |
| resolve_stop_reason() | ✅ Adopt (已实施) | — |
| CheckpointStage 重构 | ✅ Adopt (已实施) | — |
| has_xxx() | ✅ Adopt (已实施, T2) | — |
| get_metrics defensive copy | ✅ Adopt (已实施) | — |
| get_custom 保持引用 | ✅ Adopt (已实施) | — |
| `resolve_stop_reason(ctx=None)` | 🟡 Adopt (Non-blocking T1) | 实施阶段 |
| resolve_stopped_by alias | ✅ Adopt (保留) | — |
| `get_all()` | ❌ Reject | — |
| to_dict() / from_dict() | 🟡 V1.0.9 | Metadata Serialization |
| Predicate API (is_stopped 等) | 🟡 V1.0.9 | — |
| Runtime freeze | 🟡 V2 | — |
| Property-based Test | 🟡 Optional | — |

---

## V1.0.8 实施采纳调整 (Non-blocking T1)

**采纳：** `resolve_stop_reason(ctx: Optional["ExecutionContext"] = None)`
- 签名 + 实现一致 (实现已支持 None via `getattr(ctx, "metadata", None)`)
- 加 3 个测试覆盖 ctx=None 场景
- 文件: `planner/runtime_metadata.py` line 319

**V1.0.8 最终：** 42+ tests (39 原始 + 3 Non-blocking ctx=None)

---

## V1.0.8 收官下一步

1. ✅ V1.0.8 ADR-0028 Accepted (9.91/10, 8070b4e)
2. ✅ V1.0.8 Implementation (9.94/10, 4ba05b9, 42 new tests, 305+ pass)
3. 🔜 启动 V1.0.8 ADR-0029 Stage Registry (ChatGPT 9.94/10 MUST)
4. 🔜 V1.0.8 ADR-0029 ChatGPT 审核 + Accepted
5. 🔜 V1.0.8 Stage Registry 实施
6. 🔜 V1.0.8 Stage Registry 代码层 ChatGPT 审核 + Accepted
7. 🔜 V1.0.9 Metadata Serialization (to_dict() / from_dict()) + Pipeline Introspection

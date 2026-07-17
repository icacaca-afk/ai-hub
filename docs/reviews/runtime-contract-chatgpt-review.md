# Runtime Contract ChatGPT 外部审核

> 时间：2026-07-18
> 评分：**10.0 / 10 FINAL APPROVED** ✅
> 提交：6e4d523 docs: Runtime Contract 草案
> 审核 prompt：`.tmp_runtime_contract_review.txt`（3376 chars，8 个确认问题）
> 回复：约 4500 chars

---

## 总体结论

> 评分：10.0 / 10（FINAL APPROVED）
>
> 这是我认为 V0.9.x 最重要的一份文档。
>
> 原因不是它增加了任何功能，而是它把 V0.9.4～V0.9.7 四个版本逐渐形成的运行时约束，从"隐含设计"正式提升为 Runtime Contract。
>
> 这一点对于后面的 Workflow Runtime（Retry、Checkpoint、Resume、Condition、Pipeline）非常关键。
>
> 我的评价是：
>
> **ADR 决定为什么这么设计；Runtime Contract 决定以后任何人不能破坏哪些设计。**
>
> 这是两个完全不同层面的东西。

---

## V0.9.x 整体评价（⭐⭐⭐⭐⭐ 五星）

| 阶段 | 评价 |
|------|------|
| V0.9.4 Event | ⭐⭐⭐⭐⭐ |
| V0.9.5 Storage | ⭐⭐⭐⭐⭐ |
| V0.9.6 Metrics | ⭐⭐⭐⭐⭐ |
| V0.9.7 Analytics | ⭐⭐⭐⭐⭐ |
| **Runtime Contract** | ⭐⭐⭐⭐⭐ |

---

## 逐项反馈（8 个确认问题）

### Q1 6 条核心原则 — ✅ 完整，不建议增加

> 我不建议增加。
>
> 六条原则已覆盖 Runtime 最重要的不变量。

**结论**：维持 6 条原则。

### Q2 Consumer 不应抛异常 — 📝 措辞调整

**采纳**：改为"不允许异常传播"而非"不允许失败"。

**原文**：

> Consumer 不应抛异常到 EventBus（用 try/except 内化）

**改为**：

> Consumer MUST internally handle its own failures and MUST NOT allow exceptions to escape EventBus dispatch.

**强调**：

```
EventBus
    |
    +--- Consumer A failed (内部消化)
    |
    +--- Consumer B still executes (继续)
```

不是"Consumer 永远不会失败"，而是"失败必须内部消化"。

### Q3 query_events "唯一查询入口" — 📝 措辞调整

**采纳**：改为"canonical query interface"。

**原文**：

> query_events() 是唯一查询入口

**改为**：

> `query_events()` is the canonical query interface.
> Other methods (get_events / list_plans / has) are Convenience APIs.

**原因**：

- get_events() / list_plans() / has() 都还存在
- "唯一"措辞过严
- "canonical" + "Convenience API" 严格准确

### Q4 Failure Policy — 📝 强化统一日志规范

**采纳**：明确 Consumer failure 日志格式。

**改为**：

> Consumer failures SHOULD include:
> - consumer name
> - exception type
> - exception message
>
> and continue processing remaining events.

**示例**：

```
StatisticsCollector skipped event
  event_id=...
  reason=Invalid timestamp
  exception=ValueError
```

**原因**：Dashboard / Exporter / WebSocket / Metrics / Statistics 都应统一日志风格。

### Q5 MetricsRouter V2.0 退出路径 — 📝 不要写死 Decorator

**采纳**：改为"Future Runtime Layer"模糊化。

**原文**：

> V2.0 退出路径：MetricsRouter 应被 BridgeResult raw extension 或 ExecutionPipeline Decorator 替代。

**改为**：

> MetricsRouter is transitional.
> Server metrics extraction should migrate into future runtime infrastructure.

**原因**：

- V1.0 还没开始
- 以后可能变成 Pipeline / Middleware / Interceptor / Execution Runtime
- Contract 只承诺"转义"，不写死实现

### Q6 不属于 Runtime Contract — 📝 增加 Business State

**采纳**：在 "不在 Runtime Contract 范围" 增加 Business State。

**新增**：

> - ❌ Business State（如 Plan status / Task state / Course progress）— 属业务 Contract，不是 Runtime

### Q7 文档体系 — 📝 建议增加 ARCHITECTURE.md

**采纳**：V1.0 启动时增加 `docs/ARCHITECTURE.md` 作为总入口。

**结构**：

```
ARCHITECTURE.md
├── Architecture Overview
├── Component Diagram
├── Document Map
│   ├── Runtime Contract
│   ├── Provider Spec
│   ├── ADR
│   └── Glossary
```

**V1.0 并行完成**（不阻塞 Runtime Contract 应用）。

### Q8 V1.0 是否先写 ADR — ✅ 按阶段写

> 我的建议：Runtime Contract 已经足够。
>
> 不要一口气写完整 Workflow ADR。
>
> 建议按阶段：
> - ADR-0021 ExecutionPipeline → 编码 → 冻结
> - ADR-0022 Retry → 编码 → 冻结
> - ADR-0023 Checkpoint → 编码 → 冻结
>
> 不要一次写：Workflow Runtime 3000 行 ADR。
> 否则很容易：设计领先实现半年。

**结论**：维持 V0.9.x 的 ADR → 实现 → 测试 → 冻结 节奏。

---

## ChatGPT 唯一建议补充（可选）— 原则 G Runtime Determinism

> 如果允许增加一条，我会增加：
>
> **Runtime Determinism**
>
> Given the same immutable ExecutionEvent stream,
> all compliant projections MUST derive equivalent results.
>
> 中文：
> 对同一 ExecutionEvent 流，任意 Projection（Statistics、Dashboard、Exporter）
> 应得到一致的派生结果。
>
> 这是 Event Sourcing 很经典的一条。
>
> 不过这是锦上添花，不是必须。
> 如果保持六条原则，我也完全同意。

**结论**：V0.9.7 收官阶段保持 6 条；V1.0 启动时再评估是否加入。

---

## ChatGPT 文档体系最终建议

> 我建议：
> - 合并 runtime-contract.md
> - 增加一个简洁的 ARCHITECTURE.md 作为文档导航（可与 V1.0 并行完成）
>
> 进入 V1.0 时按 ADR → 实现 → 测试 → 冻结 的节奏推进，
> 每个 Workflow 能力（如 Pipeline、Retry、Checkpoint）分别独立设计和实现，
> 而不是预先设计整个运行时。
> 这样既能保持架构一致性，也能降低设计与实现脱节的风险。

---

## 最终结论

> **评分：10.0 / 10**
> **结论：FINAL APPROVED**
>
> 这份 `docs/runtime-contract.md` 可以作为 V1.0 Workflow Runtime 的正式基线文档。

---

## 采纳清单

| # | 建议 | 状态 | 落地位置 |
|---|------|------|---------|
| 1 | 6 条原则完整 | ✅ 维持 | 原则 A-F |
| 2 | Consumer 改为"失败内部消化"措辞 | 📝 采纳 | 章节 3.2 |
| 3 | query_events 改为 canonical query interface | 📝 采纳 | 章节 4.1 |
| 4 | Failure Policy 强化统一日志规范 | 📝 采纳 | 章节 6.2 |
| 5 | MetricsRouter 退出路径模糊化为 Future Runtime Layer | 📝 采纳 | 章节 8 |
| 6 | 增加 Business State 到"不在范围" | 📝 采纳 | 章节 10 |
| 7 | 建议增加 ARCHITECTURE.md（V1.0 并行） | 📝 采纳 | V1.0 任务 |
| 8 | V1.0 按阶段写 ADR | ✅ 维持 | 路线 |
| 9 | 可选：增加 Runtime Determinism 原则 | ⏸ V1.0 评估 | 未来 |

**采纳 6 项微调 + 1 项可选 + 1 个文档体系建议**

---

## V0.9.x 完整演化线（最终）

| 版本 | 主题 | ADR 评分 | 代码/Contract 评分 |
|------|------|---------|-----------------|
| V0.9.0~V0.9.2 | Planner Skeleton → LLM Planner | 9.5/10 | — |
| V0.9.3 | Inspect / PlanStore | 9.98/10 | — |
| V0.9.4 | ExecutionEvent / Trace | 10.0/10 | 10.0/10 |
| V0.9.5 | SQLiteExecutionStore | 10.0/10 | 10.0/10 |
| V0.9.6 | Provider Metrics | 9.95/10 | 10.0/10 (Final) |
| V0.9.7 | Execution Analytics | 9.95/10 | 10.0/10 (Final) |
| **Runtime Contract** | **运行时约定** | — | **10.0/10 (Final)** |

**V0.9.x Runtime Observability 阶段 + 运行时约定层全部收官 ✅**

---

## 下一步

1. → **采纳 6 项微调更新 runtime-contract.md**
2. → commit Accepted 状态 + review 记录
3. → V1.0 启动：写 ARCHITECTURE.md（文档体系入口）
4. → V1.0 第一个 ADR：ADR-0021 ExecutionPipeline

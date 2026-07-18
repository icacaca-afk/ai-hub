# ChatGPT ADR 审核 — ADR-0025 V1.0.5 PipelineHooks 草案

**ADR**: [0025-pipeline-hooks.md](../adr/0025-pipeline-hooks.md) (Proposed → Accepted)
**审核日期**: 2026-07-18
**审核工具**: ChatGPT (gpt-5-thinking) via Playwright v2

---

## 综合评分

**9.9 / 10 — APPROVED（建议合并）**

> "这是一个方向正确、边界清晰的 ADR。"

> "ADR-0021 建立 Runtime / ADR-0022 增加 Retry / ADR-0023 增加 Persistence / ADR-0024 增加 Workflow Control / ADR-0025 则开始建立 Runtime Observability。"

> "这是 Pipeline 生命周期里的第四类能力（Control、Persistence、Observability、Execution），架构方向完全正确。"

---

## 分项评分

| 维度 | 分数 |
|------|------|
| Runtime Architecture | 10.0 |
| Hook 抽象 | 10.0 |
| 生命周期设计 | 10.0 |
| Runtime Contract | 10.0 |
| Core Freeze | 10.0 |
| 扩展性 | 10.0 |
| Performance | 9.8 |
| Hook API | 9.6 |

**最终：9.9 / 10**

---

## 关键肯定

### Q1 Hook 独立于 Stage ✓

> "Hook 是 Observer, 不是 Pipeline 的一个 Stage。Stage 的职责: ExecutionContext → ExecutionContext'. Hook 的职责: ExecutionContext → None."

> "如果把 Hook 写成 Stage: LoggingStage / TracingStage / MetricsStage. 那么 Stage 数量爆炸, Pipeline 顺序开始依赖日志, Stage 开始承担副作用. 这是错误方向."

### Q2 6 个 Hook 点 ✓

> "刚刚好. 没有 before_retry / after_retry / before_checkpoint / before_condition. 这些都是 Stage 自己的内部事件. Hook 不应该知道 Retry / Checkpoint / Metrics. 否则 Hook 就开始绑定 Stage 类型."

### Q3 Hook 不修改 ctx ✓

> "千万不要 ctx2 = hook(ctx). 否则 Hook 马上变成另一种 Stage. 整个抽象立刻崩掉."

> "Hook 永远 Callable(...)->None 是最好的. 以后如果真的需要 Modify Hook. 建议单独 PipelineMiddleware. 不要污染 Hook."

### Q4 List[Hook] ✓

> "不要 HookProvider → HookChain → HookManager → Composite. 这些都是 Enterprise Java 风格. 目前 list[Callable] 已经足够."

### Q5 Best Effort ✓

> "如果 Logging 炸了, Pipeline 不能炸. 否则 Logging 就变成 Critical Path. 这是 Runtime 最忌讳的."

### Q6 Core Freeze ✓

> "修改只有 Pipeline.run() → fire(...). Stage 一个字没改. 说明 Hook 只是 Observer, 没有 Execution Logic. 这是优秀的 Runtime Boundary."

---

## 采纳调整

### 调整 #1 (Q3): Runtime Contract 增加 "observational only" MUST ✓

**ChatGPT 反馈**：
> "Hooks MUST be observational and MUST NOT participate in execution semantics."

**实施位置**：`docs/adr/0025-pipeline-hooks.md` §7 Runtime Contract

### 调整 #2 (Q5): Runtime Contract 增加 "Hook failures MUST NOT influence execution" ✓

**ChatGPT 反馈**：
> "虽然你的意思已经表达了，但把它作为一句独立的不变量会更明确。"

**实施位置**：`docs/adr/0025-pipeline-hooks.md` §7 Runtime Contract

### 调整 #3 (Q10): Runtime Contract 增加 SHOULD: FIFO order + side-effect free ✓

**ChatGPT 反馈**：
> "Hooks SHOULD execute in registration order. 以后不要 Priority, 默认 FIFO. Hooks SHOULD be side-effect free whenever practical. 例如 Tracing 可以写日志, 但是不要删文件/改数据库/发请求. Runtime Replay 才稳定."

**实施位置**：`docs/adr/0025-pipeline-hooks.md` §7 Runtime Contract

### 调整 #4 (Q7): `enabled` 属性替代 `is_empty()` ✓

**ChatGPT 反馈**：
> "建议 PipelineHooks 增加 @property enabled, 例如 if hooks.enabled: fire... 而不是 is_empty() → list → len → ... 不是为了性能, 而是代码更清晰."

**实施位置**：`planner/hooks.py` (V1.0.5 实施时实现)

---

## 不采纳（V2 / V1.x 后期）

| 建议 | 理由 |
|------|------|
| Q2 on_stop(ctx, stopped_by) → on_stop(ctx) | 保留双参数 (更明确, 避免 Hook 内部耦合 ctx.metadata 访问) |
| Q9 V1.1 Modify Hook 推迟 | 维持 V1.0.5 仅观察, Modify Hook 推迟 V1.1 |
| Q9 V1.1 Hook priority 推迟 | 维持 V1.0.5 FIFO 顺序, Priority 推迟 V1.1 |
| Q9 V1.0.6 Stage Descriptor 推迟 | V1.0.6 评估 (替代 V1.0.4 Pipeline 识别 Checkpoint 的耦合) |

---

## 路线图（ChatGPT 强烈建议）

> "V1.0.6 Stage Descriptor (name/version/experimental/always_run_after_stop/capability/idempotent). Pipeline 全部基于 Descriptor. 不再识别 Checkpoint. 这会把 V1.0.4 中唯一的轻微耦合彻底消除."

**保持路线**：
- V1.0.1 ExecutionPipeline ✓
- V1.0.2 RetryStage ✓
- V1.0.3 CheckpointStage ✓
- V1.0.4 ConditionStage ✓
- V1.0.5 PipelineHooks ← 当前
- **V1.0.6 StageDescriptor** ← 下一站

---

## 结论

**APPROVED** — 0 阻塞项，4 项立即采纳（3 项 Runtime Contract + 1 项 enabled 属性）。

立即进入 V1.0.5 Accepted + 启动实施。

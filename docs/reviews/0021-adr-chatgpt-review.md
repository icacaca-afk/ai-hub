# ADR-0021 ChatGPT 外部审核记录

> **审核版本**：ADR-0021 V1.0.1 ExecutionPipeline as Decorator / Middleware（Proposed）
> **审核时间**：2026-07-18
> **审核方式**：ChatGPT 外部 AI 专家审核
> **审核轮次**：第 1 轮
> **评分**：**9.95 / 10**
> **结论**：**FINAL APPROVED**（ADR 层，可进入代码实施阶段）

## 审核总评

ChatGPT 引言：

> "我认为这是一个很自然的 V1 起点，而且和前面的 Runtime Contract、ARCHITECTURE 文档形成了闭环。"
>
> "相比 V0.9.x，我认为这次最大的变化不是 MetricsStage，而是把 Runtime 的扩展点从继承改成了组合（Composition）。"
>
> "这实际上是在解决一个架构问题，而不是增加一个功能。"

总体三件真正重要的事：

1. **把 Router 从"越来越胖"重新拉回了"只负责 Routing"**
2. **把 Runtime 的扩展点统一到了 Pipeline**
3. **让以后所有 Runtime 能力（Retry、Checkpoint、Condition……）都遵循同一种扩展方式**

定性：**"Inheritance → Composition 迁移，是 V1 最值得做的事情。"**

## 10 个决策逐项审核

### Decision 1：ExecutionPipeline 整体架构

- **评分**：★★★★★（满分）
- **评价**：整个 ADR 最核心的部分。pre stages → bridge execute → post stages 结构以后可以非常稳定。
- **非阻塞建议**：ExecutionPipeline 最好不要知道 Metrics，只 for stage in stages: ctx = stage(ctx)。Pipeline 不认识任何 Stage（避免以后 Pipeline Special Case）。

### Decision 2：MetricsStage

- **评分**：★★★★★（满分）
- **评价**：比 MetricsRouter 更干净。之前 MetricsRouter 复制 execute() 插一句 MetricsExtractor；以后 MetricsStage 直接 ctx.bridge_result → ctx.server_metrics。职责非常清晰。

### Decision 3：RouteStage

- **评分**：9.9/10
- **评价**：基本赞同，但建议提前明确职责边界。
- **非阻塞建议**：
  > "RouteStage 不应该：bridge.run()"
  > "RouteStage 只负责：ctx.provider / ctx.bridge"
  > "真正执行 Bridge：应该属于 Pipeline Executor"
  > "否则：RouteStage 名字叫 Route，实际上却 Execute"
  > "以后 RetryStage 会比较难插"
  > "建议文档写清楚：RouteStage 负责选择 Provider/Bridge，不负责调用 Bridge。"

### Decision 4：Core Freeze

- **评分**：★★★★★（满分）
- **评价**：非常好。core/ + router/router.py + providers/ 全部不改，Pipeline 全部放 planner，完全符合 Runtime Contract。

### Decision 5：PipelineExecutor

- **评分**：★★★★★（满分）
- **评价**：Stage 不负责 new Result(...)，由 PipelineExecutor 统一 assemble。避免 MetricsStage / RetryStage / ConditionStage 都开始 new Result。职责干净。

### Decision 6：default_pipeline()

- **评分**：★★★★★（满分）
- **评价**：Factory 是必须的。default_pipeline() / minimal_pipeline() / test_pipeline() / debug_pipeline() 都会很好扩展。

### Decision 7：PlanExecutor 迁移

- **评分**：★★★★★（满分）
- **评价**：保持 API 不变，外部 PlanExecutor.execute(...)，内部 pipeline.run(...)。非常标准的 Adapter Migration，不破坏 CLI。

### Decision 8：Runtime Contract 同步

- **评分**：★★★★★（满分）
- **评价**：MetricsRouter → deprecated → Pipeline 是正确的。
- **非阻塞建议**：增加一张 Version Evolution 表：
  ```
  V0.9  MetricsRouter
  V1.0  MetricsStage
  V2.0  MetricsRouter Removed
  ```

### Decision 9：Experimental API Stability

- **评分**：★★★★★（满分）
- **评价**：成熟项目都会做。ExecutionPipeline / ExecutionStage / ExecutionContext 都标记 Experimental，以后接口可以慢慢稳定。

### Decision 10：测试策略

- **评分**：★★★★★（满分）
- **评价**：MetricsStage / RouteStage / Pipeline / Integration 不要全部混一起的拆分很合理。以后 RetryStage 能直接照抄。

## 8 个确认问题逐项回答

### Q1：ExecutionContext 不可变性

- **回答**：**支持 immutable**
- **理由**（ChatGPT）："不是 Functional Programming，而是与整个 Runtime 已经建立的 ExecutionEvent Immutable 保持一致。如果 ExecutionContext Mutable 反而是不一致的。统一 Immutable 以后 Debug 非常容易。"
- **结论**：采纳 V1.0.1 倾向方案

### Q2：Protocol 还是 ABC

- **回答**：**继续 Protocol，不要 ABC**
- **理由**：Stage 本质就是 callable(ctx) -> ctx，Protocol 足够。ABC 会增加很多样板。
- **结论**：采纳 Protocol 方案

### Q3：短路语义（**唯一值得修改的点**）

- **回答**：**建议小调整**
- **建议**（ChatGPT）：
  > 不要 `ctx.result is not None`
  > 建议 `ctx.stop = True`
  > 原因：以后 RetryStage 可能需要区分：
  > - ctx.exception（异常）
  > - ctx.retry（重试标记）
  > - ctx.result（最终结果）
  > 三种状态可能同时存在。`ctx.stop` 语义更明确。
- **重要程度**：**非阻塞，但建议 ADR 中提前写出来**
- **结论**：**采纳调整**（采纳为强建议）

### Q4：MetricsRouter Deprecated 2 版本过渡

- **回答**：**完全赞同**
- **理由**：不要一步删除，按 V1.0.1 deprecated → V1.0.2 warning → V1.0.3 remove。这是成熟开源项目的做法。
- **结论**：采纳 V1.0.1 方案

### Q5：Router.execute() 保留

- **回答**：**保留，不要删**
- **理由**：CLI、测试、第三方 Provider 都可能依赖。以后 Pipeline 内部不用，Router.execute Deprecated 即可。
- **结论**：采纳保留方案

### Q6：Pipeline 默认同步

- **回答**：**继续同步，不要 async**
- **理由**：Runtime Contract 现在全部同步。Async Pipeline 几乎意味着所有 Stage 都要重新定义。V1 不值得。
- **结论**：采纳同步方案

### Q7：Pipeline 不持久化

- **回答**：**完全同意**
- **理由**：Checkpoint 本来就是 CheckpointStage 负责。Pipeline 本身只是执行器，不要承担 Persistence。
- **结论**：采纳不持久化方案

### Q8：Scope 克制

- **回答**：**非常支持现在的范围**
- **理由**：千万不要 Pipeline + Retry + Checkpoint + Condition 一次完成。因为每一个其实都是独立 ADR。保持 0021 Pipeline → 0022 Retry → 0023 Checkpoint → 0024 Condition 的节奏最好。
- **结论**：采纳克制方案

## 1 条未来原则（V1.0+ 评估，非阻塞）

### Stage SHOULD be Side-Effect Minimal

- **定义**：Stage 尽量只修改 ExecutionContext，而不要：
  - 修改 SQLite
  - 发 Event
  - 写日志（除必要 warning）
  - 修改其他 Stage
- **理由**：Stage 的职责应该尽量局限于 ctx → ctx'。这样以后 Pipeline 才真正像 Middleware。
- **采纳**：V1.0+ 评估是否写入 Runtime Contract。当前 V1.0.1 范围内 MetricsStage 已经符合（只更新 ctx.result.metadata，不直接发事件或写 SQLite）。

## V1.0.x 路线建议（采纳）

ChatGPT 强烈建议保持顺序：

```
0021 ExecutionPipeline
  ↓
0022 RetryStage
  ↓
0023 CheckpointStage
  ↓
0024 ConditionStage
```

**理由**：

- Retry 是最基础的控制流
- Checkpoint 建立在 Retry 已经稳定的基础上
- Condition 又建立在 Checkpoint 之后
- 如果反过来，Condition 会变复杂很多

## 最终评价

> "这是我认为 ai-hub 从 V0.x 迈向 V1.x 最关键的一次架构升级。"
>
> "它并没有增加很多新功能，却完成了一次重要的架构转型：
> 1. 从 Router 继承链转向 Pipeline 组合。
> 2. 将运行时扩展点统一为 Stage。
> 3. 为 Retry、Checkpoint、Condition 等后续能力提供了稳定的扩展机制。
> 4. 保持了 Core Freeze，不破坏已有 Runtime Contract 与 Event 模型。"

## 最终评分

| 维度 | 评分 |
|------|------|
| 架构清晰度 | ★★★★★ |
| 与现有设计一致性 | ★★★★★ |
| 退出路径合理性 | ★★★★★ |
| 未来扩展性 | ★★★★★ |
| 测试覆盖度 | ★★★★★ |
| 文档质量 | ★★★★★ |
| 决策合理性 | 9.9/10（Decision 3 路线清晰度微调） |
| 风险评估完整性 | ★★★★★ |

**总分**：**9.95 / 10**

**结论**：✅ **FINAL APPROVED**（ADR 层，可进入代码实施阶段）

## 采纳调整清单

本 ADR-0021 升级 Accepted 时采纳的 ChatGPT 调整：

1. **Q3 短路语义改进**（**采纳**）：
   - 原文：`ctx.result is not None` 表示短路
   - 改为：**显式 `ctx.stop: bool = False` 字段**
   - 原因：为 Retry / Condition 留出更清晰的状态表达空间
   - 影响：ExecutionContext 增加 `stop` 字段；Stage 通过 `ctx.stop = True` 短路

2. **Decision 3 RouteStage 职责明确**（**采纳**）：
   - 原文：RouteStage 调 router.route() 设置 ctx.provider
   - 改为：**RouteStage 调 router.route() 设置 ctx.provider + ctx.bridge（selected bridge），不调 bridge.run()**
   - 原因：RouteStage 名字"Route"应只负责"选择"，不负责"执行"
   - 影响：base_execute 仍负责 bridge.run()，但 RouteStage 也设置 ctx.bridge（用于 metrics 提取等后续 Stage）

3. **Decision 8 Version Evolution 表**（**采纳**）：
   - 原文：Runtime Contract §9 新增 V1.0.1 行
   - 改为：**新增完整的 V0.9 → V1.0 → V2.0 MetricsRouter Migration 表**
   - 原因：读者一眼就明白 MetricsRouter 的退出路径

**未采纳**：

- Q3 关于 Exception / Retry 状态：未来 ADR-0022 / ADR-0023 / ADR-0024 实施时按需扩展 ctx 字段
- 未来原则 "Stage SHOULD be Side-Effect Minimal"：V1.0+ 评估

## 下一步

1. 采纳 3 项调整 → 更新 ADR-0021 为 Accepted
2. commit ADR-0021 Accepted 版本
3. 启动 V1.0.1 实施循环：
   - planner/pipeline.py
   - planner/stages/
   - planner/executor.py（内部用 pipeline）
   - router/metrics_router.py（加 @deprecated）
   - docs/runtime-contract.md（§2 + §8 + §9 调整）
   - 完整测试
4. 实施完成后再次发 ChatGPT 审核（代码层）

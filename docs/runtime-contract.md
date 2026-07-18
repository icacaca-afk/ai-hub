# AI Hub — Runtime Contract

> **版本**：v1.0.0（Accepted，V0.9.7 收官后启动）
> **状态**：Accepted（ChatGPT 外部审核 10.0/10 FINAL APPROVED）
> **日期**：2026-07-17
> **重要性**：与 [PROVIDER_SPEC.md](PROVIDER_SPEC.md) 同级
> **触发建议**：[V0.9.7 代码 ChatGPT Review](reviews/V0.9.7-code-chatgpt-review.md) — ChatGPT 强烈建议在 V1.0 Coding 之前完成
> **本版审核**：[Runtime Contract ChatGPT Review](reviews/runtime-contract-chatgpt-review.md) — 10.0/10 FINAL APPROVED

## 目的

把 V0.9.4（ExecutionEvent）~ V0.9.7（Execution Analytics）形成的运行时约定正式固化，避免 V1.0+（Workflow Runtime）扩展时破坏已经成熟的设计原则。

> ChatGPT 引言：
> "它的价值不是增加功能，而是把已经形成的运行时约定正式固化。"

## 1. 范围

**Runtime Contract 回答以下问题**：

- ExecutionEvent 在 Runtime 中如何流转？
- EventBus / Consumer / Storage 之间有什么保证？
- 哪些事 Runtime 永远不该做？
- 当 Event 数据有缺陷时，Runtime 如何应对？

**Runtime Contract 不回答**：

- Provider 如何实现（见 [PROVIDER_SPEC.md](PROVIDER_SPEC.md)）
- Bridge 如何实现（见 core/bridge.py）
- Planner 如何分解任务（见 planner/）

## 2. 核心原则

### 原则 A：ExecutionEvent 是 Source of Truth（事实）

**唯一原则**：

> Runtime 中所有执行状态的"事实" = ExecutionEvent 流。
>
> 任何其他数据结构（PlanStore / Step.status / ExecutionMetrics）都是 ExecutionEvent 的**派生视图**。

**衍生**：

- PlanStore 的 plan_id 对应 ExecutionEvent 的 plan_id
- Step.status 由 step_started/step_finished 派生，不存储
- ExecutionMetrics 由 provider_finished.data.server_metrics 派生，不存储

**违反示例**（不应该的）：

```python
# ❌ 错误：直接修改 PlanStore
plan_store.update_step_status(plan_id, step_id, "running")

# ✅ 正确：发射 ExecutionEvent，让 Consumer 派生
self._emit_event("step_started", plan_id=..., step_id=...)
```

### 原则 B：ExecutionEvent 不可变（Immutable）

**唯一原则**：

> ExecutionEvent 一旦被 emit，任何代码（包括 Executor / Consumer / Storage / Statistics）都**不应修改**它的任何字段。

**衍生**：

- `event_id` 一旦生成，永不修改
- `data` 字典不应被 Consumer 修改（Read-Only Projection 原则）
- 同一 event_id 重复 INSERT 时，Storage 应 warn 而非覆盖

**ChatGPT V0.9.7 特别提醒**：

> "Event Sourcing 最大的问题之一就是 Analytics 慢慢开始修改 Event。
> 你这里提前把这条原则固定下来，是一个长期收益很大的决定。"

### 原则 C：Analytics Never Mutates Events（Read-Only Projection）

**唯一原则**：

> StatisticsCollector / Analytics 任何层都**不应修改** ExecutionEvent，**不应写回** Storage，**不应缓存** ExecutionEvent。

**衍生**：

- `StatisticsCollector.compute(events)` 是纯函数（无副作用）
- 测试 `test_compute_does_not_modify_input_events` 永远为真
- Analytics 失败不应影响 Execution 主流程

**ChatGPT V0.9.7 唯一补充原则**：

> "StatisticsCollector MUST be a pure read-only projection.
> 绝不修改 ExecutionEvent，也绝不写回 ExecutionStore。"

### 原则 D：Storage is Disposable（V1.0 保留）

**唯一原则**：

> SQLiteExecutionStore / Future Storage 都不是 Source of Truth。Storage 可以被清空、被替换、被删除，ExecutionEvent 流仍可由 EventBus + TraceCollector 在内存中重建。

**衍生**：

- DB 文件可删，下次执行时自动重建
- Storage Failure 不应影响 Execution（已在 V0.9.5 实现）
- V1.0 切换 Storage（如 PostgreSQL / S3）不需要改 Executor

### 原则 E：Postel's Law（发送保守，接收宽容）

**唯一原则**：

> Producer 写最小公约数字段，Consumer 容忍未知字段。

**应用**：

- 新增 `data` 子键（如 `server_metrics`）**不**升级 schema_version
- 老 Consumer 读不到新字段静默忽略
- 新 Consumer 读老字段用 `.get(key, default)` 容错

**metadata.schema_version 维持 "1"**（V0.9.6~V0.9.7 多次确认）。

### 原则 F：ExecutionMetrics vs server_metrics 分层（V0.9.6）

**唯一原则**：

> Runtime 消费 ExecutionMetrics（标准指标），不直接消费 server_metrics（Provider 原始指标）。

**分层**：

```
Provider Bridge
    │
    ▼ BridgeResult.raw (HTTP body JSON)
    │
MetricsRouter (router/metrics_router.py) ← Core Freeze 临时层
    │
    ▼ server_metrics (extracted dict)
    │
PlanExecutor
    │
    ▼ ExecutionMetrics (latency_ms, token_in, token_out, cost_usd)
    │
ExecutionEvent.data
```

**V1.0.1 退出路径（采纳）**：MetricsRouter 标记 @deprecated，由 ExecutionPipeline 的 MetricsStage 替代（见 [ADR-0021](adr/0021-execution-pipeline.md)）。
**V1.0.3 删除**：MetricsRouter 正式删除。

## 3. EventBus 保证

### 3.1 EventBus 是同步广播

**保证**：

- `EventBus.emit(event)` 同步调用所有已订阅的 Consumer
- Consumer 按订阅顺序串行调用
- 单个 Consumer 抛异常**不应**影响其他 Consumer 和 emit 主流程

### 3.2 Consumer 责任

**Consumer 必须**：

- 实现 `handle(event: ExecutionEvent) -> None` 方法
- 容忍重复 event_id（immutable 原则）
- 容忍 event.data 字段缺失（Postel's Law）
- 不阻塞超过 100ms（V0.9.5 阈值，V1.0 重新评估）

**Consumer 不应**：

- 修改 event 任何字段
- 调用其他 Consumer 的方法
- 让异常传播到 EventBus（必须内部消化，**ChatGPT Q2 调整**）

> **ChatGPT Q2 措辞**：
> Consumer MUST internally handle its own failures and MUST NOT allow exceptions to escape EventBus dispatch.
>
> 不是"Consumer 永远不会失败"，而是"失败必须内部消化"：
> ```
> EventBus
>     |
>     +--- Consumer A failed (内部消化)
>     |
>     +--- Consumer B still executes (继续)
> ```

**标准 Consumer**：

- `InMemoryTraceCollector`（V0.9.4）— 进程级环形缓冲
- `SQLiteExecutionStore`（V0.9.5）— 持久化

两者都是独立 Consumer，**互不继承、互不引用**（ChatGPT V0.9.4 明确建议）。

## 4. Query Contract

### 4.1 query_events() 是 canonical query interface

**保证**：

- `SQLiteExecutionStore.query_events(...)` 是 **canonical query interface**（ChatGPT Q3 调整）
- 6 个 Optional 过滤参数 + limit
- provider 参数支持 `str | list[str] | None`（V0.9.7 ChatGPT Q7）
- 返回 `list[ExecutionEvent]`（按 timestamp 升序）

**旧接口保留**（Convenience API）：

- `get_events(plan_id)` ≡ `query_events(plan_id=plan_id)`
- `list_plans(limit)` 内部基于 `query_events(event_type="plan_started")` 派生
- `has(plan_id)` 保留单条 SQL EXISTS

> **ChatGPT Q3 措辞调整**：
> 不要写"唯一查询入口"（get_events / list_plans / has 仍存在）。
> 改为 `query_events()` is the **canonical query interface**。
> Other methods are **Convenience APIs**.

### 4.2 SQL 安全

**保证**：

- 所有过滤条件用参数化查询（`?` 占位符）
- `provider=list[str]` 走 `IN (?, ?, ?)` 子句
- **不**接受字符串拼接 SQL

## 5. Statistics Contract

### 5.1 StatisticsCollector 是纯 Read-Only Projection

**保证**：

- `StatisticsCollector.compute(events: list[ExecutionEvent]) -> ExecutionStatistics` 是纯函数
- 不修改入参 events
- 不接触 SQLite / EventBus
- 不缓存
- 不写回

**测试保障**：

- `test_compute_does_not_modify_input_events` 永远为真
- `test_compute_pure_function_same_input_same_output` 永远为真

### 5.2 派生而非存储

**保证**：

- `ExecutionStatistics` 所有字段都从 `ExecutionEvent` 派生
- 不调 `PlanStore`（PlanStore 是业务视图，不是执行视图）
- 不调 `InMemoryTraceCollector`（内存，不是历史）
- 单次遍历 events 完成全部聚合

## 6. Failure Policy

### 6.1 Storage Failure ≠ Execution Failure

**保证**（V0.9.5）：

- `SQLiteExecutionStore.handle()` 内 catch 所有 sqlite 异常
- log 但不 re-raise
- 持久化失败不影响执行主流程

### 6.2 Analytics Failure ≠ Storage Failure

**保证**（V0.9.7 + V1.0 强化）：

- `StatisticsCollector.compute()` 解析失败时 skip 该条（不抛异常）
- 时间戳损坏 → warning + 跳过该条 latency
- 整个统计不会因单条 event 失败而崩溃

**V1.0 强化**（ChatGPT V0.9.7 Q6 + Runtime Contract Q4 建议）：

- StatisticsCollector 解析失败时显式 warning
- 跳过该条，不影响整体

**Consumer failure 统一日志规范**（ChatGPT Q4 强化）：

Consumer failures SHOULD include:
- consumer name
- exception type
- exception message

and continue processing remaining events.

**示例**：

```
StatisticsCollector skipped event
  event_id=...
  reason=Invalid timestamp
  exception=ValueError
```

**原因**：Dashboard / Exporter / WebSocket / Metrics / Statistics 都应统一日志风格。

## 7. Capability Routing 不变量

**保证**（V0.9.0 以来持续维护）：

- Provider 不可执行 execute()（见 PROVIDER_SPEC.md）
- Router 决定"哪个 Provider"，Provider 决定"如何调用"
- Capability 是第一公民，Provider 是实现细节
- V1.0+ Capability 仍是首要约束

## 8. Core Freeze 边界

**保证**（ADR-0008）：

- `core/` — 永远只读（provider / bridge / result / task）
- `router/router.py` — 永远只读
- `providers/` — 永远只读
- 新增能力通过**子类化**或**新文件**实现

**V0.9.6 MetricsRouter 临时层**：

- 解决 Core Freeze 下"无法在 Router.execute() 加 server_metrics"
- **MetricsRouter is transitional**（ChatGPT Q5 措辞调整）
- **Server metrics extraction should migrate into future runtime infrastructure**
- **V1.0.1 实施决定**（[ADR-0021](adr/0021-execution-pipeline.md)，9.95/10 FINAL APPROVED）：
  - 选择 **ExecutionPipeline as Decorator / Middleware** 路径
  - `MetricsStage` 取代 MetricsRouter.execute() 装饰
  - MetricsRouter 标记 @deprecated（V1.0.3 删除）

**V1.0.1 ExecutionPipeline 抽象**（[ADR-0021](adr/0021-execution-pipeline.md)）：

- `ExecutionContext` 不可变（`with_xxx` 每次返回新对象）
- Stage 通过 Protocol 接口 `__call__(ctx) -> ctx` 介入
- 短路语义：`ctx.stop: bool` 字段（显式标志，替代 `ctx.result is not None`）
- `ExecutionPipeline.run(task)` 是 V1.0+ 标准执行入口

## 9. 版本演进

| 版本 | Runtime Contract 影响 |
|------|---------------------|
| V0.9.4 | 引入 ExecutionEvent + EventBus + TraceCollector |
| V0.9.5 | 引入 SQLiteExecutionStore（独立 Consumer） |
| V0.9.6 | 引入 ExecutionMetrics / server_metrics 分层（原则 F） |
| V0.9.7 | 引入 query_events() 统一查询 + StatisticsCollector Read-Only Projection（原则 C） |
| V1.0.0 | ARCHITECTURE.md Accepted（10.0/10 FINAL）；Runtime Contract Accepted（10.0/10 FINAL） |
| V1.0.1 | 引入 ExecutionPipeline as Decorator / Middleware（ADR-0021 9.95/10）；MetricsRouter Deprecated（V1.0.3 删除） |
| V1.0.2 | 引入 RetryStage（ADR-0022 规划） |
| V1.0.3 | 引入 CheckpointStage（ADR-0023 规划）；**删除 MetricsRouter** |
| V1.0.4 | 引入 ConditionStage（ADR-0024 规划） |

**MetricsRouter 迁移路径**（ADR-0021 采纳）：

```
V0.9  MetricsRouter (V0.9.6 临时层引入)
            ↓
V1.0  MetricsStage (V1.0.1 ExecutionPipeline 引入)
            ↓
V2.0  MetricsRouter Removed (V1.0.3 实施)
```

## 10. 不在 Runtime Contract 范围

以下内容**不**在本 Contract 范围（避免范围蔓延）：

- ❌ Provider 接口规范（见 [PROVIDER_SPEC.md](PROVIDER_SPEC.md)）
- ❌ Bridge 接口规范（见 core/bridge.py）
- ❌ Planner 分解策略（见 planner/）
- ❌ CLI 命令规范（见 cli/）
- ❌ Pricing 估算准确度（V0.9.6 chatgpt 已确认是估算）
- ❌ 持久化 Storage 实现（SQLite / Future）
- ❌ Dashboard / Web UI（V1.0+ 推迟）
- ❌ **Business State**（如 Plan status / Task state / Course progress）— 属业务 Contract，不是 Runtime（ChatGPT Q6 补充）

## 11. 与其他文档的关系

```
ARCHITECTURE.md（V1.0 启动时新增，ChatGPT Q7 建议）
├── Architecture Overview
├── Component Diagram
└── Document Map
    ├── Runtime Contract（本文件）
    ├── PROVIDER_SPEC.md
    ├── Capability Contract（V1.0+ 评估）
    └── Workflow Contract（V1.0+ 启动）
```

```
PROVIDER_SPEC.md       Runtime Contract
  │                          │
  ▼                          ▼
Provider 实现         Runtime 行为
（怎么调用）          （怎么执行）
  │                          │
  └──────────┬───────────────┘
             ▼
         ai-hub 整体行为
```

## 12. 后续

- 本 Contract 已通过 ChatGPT 外部审核（10.0/10 FINAL APPROVED）
- V1.0 启动前置：写 `docs/ARCHITECTURE.md`（ChatGPT Q7 建议）
- V1.0 按阶段写 ADR（不一口气写完整 Workflow）：
  - ADR-0021 ExecutionPipeline → 编码 → 冻结
  - ADR-0022 Retry → 编码 → 冻结
  - ADR-0023 Checkpoint → 编码 → 冻结
- V1.0+ 任何 Runtime 行为变更需更新本 Contract

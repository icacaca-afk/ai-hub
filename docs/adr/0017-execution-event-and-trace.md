# ADR-0017: V0.9.4 — Execution Event + Metrics + Trace

- **状态**: Accepted（ChatGPT 外部审核 10.0/10 APPROVED）
- **日期**: 2026-07-17
- **里程碑**: V0.9.4
- **关联**: ADR-0008（Core Freeze）、ADR-0013（Planner 骨架）、ADR-0014（CLI + metadata 分层）、ADR-0015（LLM Planner + 语义）、ADR-0016（CLI --json + inspect + schema_version）
- **API Stability**: Experimental
- **ChatGPT 审核**: 10.0/10 APPROVED（2026-07-17）
- **前序审核**: [V0.9.3 ChatGPT Review](../reviews/V0.9.3-chatgpt-review.md) — 9.98/10 APPROVED

## ⚠️ 核心设计原则（ChatGPT 审核强建议加入）

> **ExecutionEvent 是 Runtime 唯一的执行事件来源（Single Source of Execution Truth）**
>
> 所有 Trace、Metrics、History、UI 都应基于 ExecutionEvent 派生，而不是直接读取 Executor 内部状态。
>
> ```
> Executor
>    │
>    ▼
> ExecutionEvent
>    │
>    ├── TraceCollector (V0.9.4)
>    ├── MetricsCollector (V0.9.5+)
>    ├── SQLite ExecutionStore (V0.9.5+)
>    ├── JSON Exporter (V0.9.4+)
>    └── Future UI
> ```
>
> 以后新增任何观察能力，都不用侵入 Executor。

**实施影响**：
- `PlanExecutor` 内部不再提供 get_trace() / get_metrics() 这类方法
- 所有可观察数据通过 EventBus 流出，由 Consumer 派生
- PlanExecutor.execute() 只关心 emit，不关心 consume

## 背景

V0.9.3 完成了 Planner 的"用户接口"——`ai-hub plan --json` + `ai-hub inspect <plan_id>`。ChatGPT 审核 9.98/10 APPROVED。

但 V0.9.3 的 `inspect` 只展示**最终状态**（Plan + Step 的 success/failed）。用户看到的是「结果」，看不到**过程**。

ChatGPT V0.9.3 审核明确建议 V0.9.4 方向（按优先级）：

1. **第一**：Execution Event 模型（不是 SQLite）
2. **第二**：ExecutionMetrics（与 ExecutionResult 解耦）
3. **第三**：Trace 视图（比 SQLite 更重要）

并提出关键架构抽象：

> 从现在开始区分：**Plan**（业务）/ **Execution**（执行过程）/ **History**（历史持久化）。
> 不要让 PlanStore 慢慢演变成 ExecutionStore。

## 目标

把 Planner 从"做完了什么"推进到"做了什么、花了多久、调用了谁"。

## 决策

### 决策 1：引入 ExecutionEvent 模型（V0.9.4 第一优先级）

**Event 类型**（受 ChatGPT 建议）：

| 类型 | 触发时机 | 携带字段 |
|------|----------|----------|
| `plan_started` | PlanExecutor.execute 入口 | task_id |
| `planner_started` | Planner.decompose 入口 | task_id |
| `planner_finished` | Planner.decompose 返回 | plan_id, step_count, planner |
| `step_started` | 每个 Step 开始执行 | step_id, content_preview, capabilities |
| `provider_selected` | Router 选定 Provider | step_id, provider, score |
| `provider_finished` | Provider.execute 返回 | step_id, provider, status, latency_ms |
| `step_finished` | 每个 Step 结束 | step_id, status, latency_ms |
| `plan_finished` | PlanExecutor.execute 出口 | plan_id, status, total_latency_ms |

**数据结构**：

```python
# planner/execution_event.py（新增）
import uuid

@dataclass
class ExecutionEvent:
    type: str                        # event type (上述表格)
    timestamp: str                   # ISO 8601
    plan_id: str                     # 关联 Plan
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)  # 唯一键（ChatGPT 建议）
    step_id: str | None = None       # 关联 Step（plan-level event 为 None）
    provider: str | None = None      # provider-level event 携带
    latency_ms: int | None = None    # 显式仅记录 Provider latency（Step/Plan 由 Consumer 派生）
    data: dict[str, Any] = field(default_factory=dict)
```

**为什么加 event_id？**（ChatGPT 建议）

未来：Execution History / Replay / Filtering 都需要唯一键。timestamp 不是唯一键。

### 决策 2：EventBus（事件分发）

**简单实现**（V0.9.4 不引入复杂总线）：

```python
# planner/event_bus.py（新增）
class EventBus:
    """进程内事件总线（单线程，订阅者同步回调）。

    V0.9.4 简单实现：list of callable subscribers。
    V0.9.5+ 持久化或并发场景时，可替换为 SQLite/Redis 持久化总线。

    API Stability: Experimental
    """

    def subscribe(self, event_type: str | None, handler: Callable[[ExecutionEvent], None]) -> None:
        """订阅事件。

        Args:
            event_type: 事件类型（V0.9.4 内部暂不过滤，传 None 表示订阅所有）。
                       接口预留以保证未来可升级（ChatGPT 建议）。
            handler: 回调函数（同步执行，异常 try/except 隔离）。
        """

    def emit(self, event: ExecutionEvent) -> None:
        """同步分发事件。"""

    def clear(self) -> None:  # 测试用
        ...
```

**为什么简单实现？**
- 单进程单线程（CLI 顺序调用），不需要 async
- 订阅者模式允许未来加 SQLite consumer / 内存 trace / 日志，无需改 emit 端
- ChatGPT：「SQLite / JSON / Memory 都只是 Consumer」

**不引入**（ChatGPT 强建议）：
- ❌ priority（优先级）
- ❌ wildcard（通配符订阅）
- ❌ event hierarchy（事件继承）
- ❌ async（异步分发）
- ❌ sticky event（粘性事件）

这些都会增加维护成本，V0.9.5+ 需要时再升级。

### 决策 3：ExecutionMetrics（与 ExecutionResult 解耦）

**ChatGPT 关键洞察**：

> 不要把 latency / token / cost 直接塞进 ExecutionResult。
> ExecutionResult 以后容易越来越胖。
> 建议单独 ExecutionMetrics { latency_ms / token_in / token_out / cost / retry }。

**新数据结构**（只含可测量字段，ChatGPT 强建议）：

```python
# planner/execution_metrics.py（新增）
@dataclass
class ExecutionMetrics:
    """可测量的执行指标。

    只包含「可测量」字段（ChatGPT 强建议）：
    - latency / token / cost / retry
    不含：status / provider / error（这些不是 Metrics，是 Result）。
    """
    latency_ms: int = 0
    token_in: int = 0
    token_out: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0
    # 未来扩展（保留字段，不启用）
    # cache_hit: bool = False
    # queue_wait_ms: int = 0
    # network_latency_ms: int = 0
    # provider_latency_ms: int = 0
```

**挂在哪？** — Plan 与 Step 两层都有 metrics：
- `Step.execution_metrics: ExecutionMetrics | None`（每步独立）
- `Plan.aggregate_metrics: ExecutionMetrics`（聚合）

V0.9.4 只填 `latency_ms`（最简单）。`token_*` / `cost` 留 V0.9.5+ 与 Provider 配合。

### 决策 4：ExecutionRecord 抽象（为 V0.9.4+ 铺路）

**ChatGPT 长期建议**：

```python
@dataclass
class ExecutionRecord:
    plan: Plan              # 业务计划
    events: list[ExecutionEvent]   # 执行过程
    metrics: ExecutionMetrics      # 聚合指标
    result: Result          # 最终结果
```

**V0.9.4 只预留抽象**，不实现完整的 ExecutionRecord 类。PlanStore 仍存 Plan，但每个 Plan 可通过 `_execution_events` 字段（V0.9.4 新增）携带事件流。

**为什么不在 V0.9.4 完全重构？**
- PlanStore 已被 V0.9.3 锁定为"plan cache"
- V0.9.4 仍保持 PlanStore 职责不变，但为 V0.9.5+ 引入 ExecutionStore 留接口
- 增量演进（不破坏现有 inspect 用户体验）

### 决策 5：Plan 与 Step 增加 `events` 字段（向后兼容）

```python
# planner/plan.py（修改）
@dataclass
class Plan:
    ...
    events: list[ExecutionEvent] = field(default_factory=list)  # V0.9.4 新增
    aggregate_metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)

@dataclass
class Step:
    ...
    events: list[ExecutionEvent] = field(default_factory=list)  # V0.9.4 新增
    execution_metrics: ExecutionMetrics | None = None
```

**为什么不引入 ExecutionRecord 类？** —— 避免破坏 V0.9.3 inspect 用户的 API 稳定性。Plan.events 作为可选字段，老代码不受影响。

### 决策 6：PlanExecutor 集成 EventBus

**注入方式**（V0.9.4）：

```python
# planner/executor.py（修改）
class PlanExecutor:
    def __init__(
        self,
        router: Router,
        planner: Optional[Planner] = None,
        plan_store: Optional[PlanStore] = None,
        event_bus: Optional[EventBus] = None,  # V0.9.4 新增
    ):
        ...
        self.event_bus = event_bus

    def execute(self, task: Task) -> Result:
        # 每个关键节点 emit
        self._emit("plan_started", plan_id=None, ...)
        ...
```

**可选注入**（向后兼容）：`event_bus=None` 时不 emit（默认行为），V0.9.4 CLI 注入 `InMemoryTraceCollector` 订阅者（见决策 7）。

### 决策 7：InMemoryTraceCollector（trace 视图后端）

**简单实现**（V0.9.4 不持久化）：

```python
# planner/trace_collector.py（新增）
class InMemoryTraceCollector:
    """进程内 Trace 收集器（订阅 EventBus，存最近 N 个 plan 的 events）。

    与 PlanStore 类似：环形缓冲，不持久化。
    区别：
    - PlanStore 存 Plan（业务）
    - TraceCollector 存 events（过程）
    """

    def __init__(self, max_plans: int = 10):
        self._events: dict[str, list[ExecutionEvent]] = {}
        self._max = max_plans

    def attach(self, bus: EventBus) -> None:
        """订阅 EventBus（V0.9.4 订阅所有 event_type）。"""
        bus.subscribe(None, self.handle)

    def handle(self, event: ExecutionEvent) -> None:
        """EventBus 回调：存到对应 plan_id 的 events 列表。"""

    def get_trace(self, plan_id: str) -> list[ExecutionEvent]: ...
    def has(self, plan_id: str) -> bool:
        """是否有该 plan_id 的 trace（ChatGPT 建议 D5：建立关联）。"""
        return plan_id in self._events
    def list_traced_plans(self) -> list[str]: ...
    def clear(self) -> None: ...  # 测试用
```

**为什么独立于 PlanStore？** —— ChatGPT 建议（D5）：

> PlanStore 回答「发生了什么？」，Trace 回答「怎么发生的？」
> 不要统一 Store。建立关联：
> - TraceCollector.has(plan_id)
> - PlanStore.trace_available
> - inspect 显示 "Trace: Available/No Trace"

**V0.9.4 实施**：
- TraceCollector.has(plan_id) 强制实现
- PlanStore 在 V0.9.4 不修改（V0.9.5+ 加 trace_available）
- `cli/inspect` 显示 "Trace: Available" 或 "Trace: No Trace"

### 决策 8：ai-hub trace 命令（Timeline 视图）

**新增 CLI**：

```
ai-hub trace <plan_id>           Timeline（人类可读）
ai-hub trace <plan_id> --json    Timeline JSON
ai-hub trace --list              列出被 trace 的 plan_id
```

**Timeline 输出示例**（人类可读，ChatGPT 强建议）：

```
AI Hub Trace — v0.9.4 (Current Process Only)

Plan: fake-plan-001
Task: task-fake-plan-001
Status: SUCCESS

Timeline (8 events):
  12:01:00.000  0.0s  plan_started
  12:01:00.001  0.0s  planner_started (RuleBasedPlanner)
  12:01:00.020  0.0s  planner_finished (2 steps)
  12:01:00.100  0.1s  step_started [step-0: hello]
  12:01:00.105  0.1s  provider_selected (ScoreRouter → fake)
  12:01:00.305  0.3s  provider_finished (fake, 200ms)
  12:01:00.305  0.3s  step_finished [step-0: SUCCESS, 200ms]
  12:01:00.500  0.5s  plan_finished (SUCCESS, 500ms)
```

**ChatGPT 建议（D6）**：trace 是 Timeline，不是 log。所以：
- 真实时间戳（`12:01:00.000`）
- 相对时间（`0.0s`, `0.3s`）
- 派生 Step/Plan latency（不显式记录 Event.latency，只记 Provider）

**Trace JSON schema**：

```json
{
  "version": "0.9.4",
  "plan_id": "fake-plan-001",
  "task_id": "task-fake-plan-001",
  "status": "success",
  "total_latency_ms": 500,
  "events": [
    {"type": "plan_started", "timestamp": "...", "latency_ms": null, ...},
    {"type": "step_finished", "timestamp": "...", "step_id": "step-0", "latency_ms": 200, ...}
  ]
}
```

### 决策 9：Core Freeze 维持

- core/ + router/ + providers/ 0 修改
- V0.9.4 全部新增 / 修改在 `planner/` + `cli/`
- EventBus 是 planner 内部组件，不污染 Router 抽象

### 决策 10：schema_version 维持 "1"（不升级到 "2"）

**ChatGPT 关键建议**：

> **Schema Version 只因为 JSON Contract 变化而变化。不要因为新增字段就升级。**
> 例如：如果只是新增 Optional 字段，Schema 未破坏，我不会升级。
> 我建议：只有 Consumer 必须修改，才 Schema Version++。否则 Version Inflation。
>
> Postel's Law：Be conservative in what you send, be liberal in what you accept.
> Consumer 永远容忍缺字段（latency_ms = None 而不是抛异常）。

**V0.9.4 决策**：
- `metadata.schema_version` 维持 `"1"`（不升级）
- V0.9.4 新增字段（`aggregate_metrics` / `step.execution_metrics` / `events`）都是 **Optional**
- 老 consumer 缺字段时静默忽略
- V0.9.4 文档强化 Postel's Law 兼容性原则

**未来升级触发条件**（V0.9.5+）：
- 字段类型变化（如 ExecutionMetrics.latency_ms: int → float）
- 字段语义变化（如 ExecutionMetrics.cost_usd 含义改变）
- 字段强制化（Optional → Required）
- **不要**因为新增 Optional 字段就升级

**Decision Reversal**：原 ADR-0017 拟升级 "1" → "2"，按 ChatGPT 建议改回 "1"。

## 架构

```
┌─────────────────────┐
│ PlanExecutor        │
│   .execute(task)    │
│                     │
│   emit("plan_...") ─┼──→ EventBus ──→ InMemoryTraceCollector (V0.9.4)
│   emit("step_...") ─┤        │
│   emit("provider...")        │
└─────────────────────┘         │
        │                       │
        ↓                       ↓
    PlanExecutor             events[plan_id]
        │                       │
        ↓                       │
    Plan + events              │
    + execution_metrics        │
        │                       │
        ↓                       ↓
    PlanStore (V0.9.3)      TraceCollector (V0.9.4)
        │                       │
        ↓                       ↓
    ai-hub inspect         ai-hub trace
    (业务视图)              (过程视图)
```

**关键解耦**：
- `inspect` 查 PlanStore（业务）
- `trace` 查 TraceCollector（过程）
- 两者共享 `plan_id` 关联

## 范围

### 只做

1. `planner/execution_event.py`（新增）— `ExecutionEvent` 数据类
2. `planner/execution_metrics.py`（新增）— `ExecutionMetrics` 数据类
3. `planner/event_bus.py`（新增）— `EventBus` 进程内总线
4. `planner/trace_collector.py`（新增）— `InMemoryTraceCollector` 订阅者
5. `planner/plan.py`（修改）— Plan/Step 加 `events` + `execution_metrics` 可选字段
6. `planner/executor.py`（修改）— execute() 关键节点 emit 事件
7. `cli/trace.py`（新增）— `ai-hub trace` 命令
8. `cli/main.py`（修改）— 注册 trace 命令
9. `cli/plan.py`（修改）— 注入 EventBus + InMemoryTraceCollector 单例
10. `metadata.schema_version = "1"`（维持，不升级 — ChatGPT 强建议）
11. `planner/__init__.py`（修改）— 导出新类型
12. 完整测试

### 不做（V0.9.5+ 推迟）

- ❌ 持久化（SQLite / Memory Bus）— ChatGPT：「SQLite 只是 Storage，不是 Runtime」
- ❌ 跨进程 EventBus — V0.9.4 单进程
- ❌ 异步事件分发（async / queue）— V0.9.4 同步回调
- ❌ Token / cost 自动采集 — V0.9.4 只填 latency_ms，token/cost 留 V0.9.5+ 与 Provider 配合
- ❌ ExecutionStore 取代 PlanStore — V0.9.4 仍保留 PlanStore，新增 TraceCollector
- ❌ 修改 core/ + router/ + providers/

## 测试策略

按 V0.9.x 一贯原则：**先 ADR → 编码 → 全量测试 → ChatGPT 审核**。

测试覆盖：
- `test_execution_event.py` — Event 数据类（构造 / to_dict / 字段）
- `test_execution_metrics.py` — Metrics 数据类（聚合 / 默认值）
- `test_event_bus.py` — Bus 订阅 / 取消订阅 / 异常隔离
- `test_trace_collector.py` — 收集 / 环形缓冲 / 边界
- `test_cli_trace.py` — trace 命令（人类可读 / --json / --list / 错误）
- `test_planner.py` — PlanExecutor emit 事件（V0.9.4 升级）
- `test_cli_plan.py` — schema_version="2" 升级兼容
- `test_cli_inspect.py` — V0.9.4 升级（业务视图不受影响）

目标：测试基线从 142 → 200+ passed。

## 兼容性

- `PlanStore` API 不变（仍存 Plan）
- `PlanExecutor.__init__` 新增可选参数 `event_bus=None`（老代码不变）
- `metadata.schema_version` 从 `"1"` → `"2"`
  - 老 consumer 读到 `"2"` 时可选择性消费 metrics 字段
  - 老 consumer 读到 `"1"` 时（V0.9.3 数据）继续工作
- `cli/plan` `--json` 输出 schema 升级（顶层加 `version: "0.9.4"`，但 plan.* 子键不变）

## 风险

| 风险 | 缓解 |
|------|------|
| EventBus 订阅者抛异常影响主流程 | `_safe_emit` 包裹 try/except，订阅者失败仅记录 |
| schema_version="2" 升级破坏老 consumer | 老 consumer 不识别 metrics 字段时静默忽略（Optional） |
| InMemoryTraceCollector 占用内存 | max_plans=10 限制（DEFAULT_TRACE_SIZE 常量） |
| emit 频繁调用影响性能 | V0.9.4 数据量小（每 plan 8-12 events），未观察到瓶颈；V0.9.5+ 再优化 |

## 后续路线

- **V0.9.5**：ExecutionStore（SQLite 单文件持久化，单进程） + 异步 EventBus
- **V0.9.6**：token / cost 自动采集（与 Provider 配合）
- **V0.10**：Workflow Runtime（按 ChatGPT 优先级）
  1. **Dependency**（依赖图 — DAG 是一种表示）
  2. **Conditional**（条件分支）
  3. **Retry**（per-step max_retries）
  4. **Checkpoint**（检查点）
  5. **Resume**（恢复）
- **V0.11+**：Multi-process EventBus（File Lock / Retry / Busy Timeout）— 仅在真实 Daemon 需求时

---

## 审核结论

> ChatGPT：10.0/10 APPROVED（Proposed → Accepted）
>
> 原文：*「我给 10.0/10（作为 ADR，而不是代码实现）。原因很简单：它没有急着做 ExecutionStore，而是先把 Execution 的模型定义出来。这是 V0.9.x 最重要的一次架构决策。」*
>
> 完整审核：[V0.9.4 ADR ChatGPT Review](../reviews/V0.9.4-adr-chatgpt-review.md)

**采纳的 8 项建议**：
1. ✅ ExecutionEvent.event_id 字段（UUID 唯一键）
2. ✅ EventBus.subscribe(event_type, callback) 接口预留（V0.9.4 内部暂不过滤）
3. ✅ ExecutionMetrics 只含可测量字段（latency / token / cost / retry）
4. ✅ ExecutionRecord 概念预留，V0.9.4 不实现完整类
5. ✅ TraceCollector.has(plan_id) + inspect 显示 "Trace: Available/No Trace"
6. ✅ trace 命令强调 Timeline（含真实时间戳 + 相对时间）
7. ✅ schema_version 维持 "1"（Postel's Law — 不为新增 Optional 字段升级）
8. ✅ Provider latency 显式记录 + Step/Plan latency 派生

**未采纳的延后**：
- ⏸ SQLite 跨进程同步（V0.9.5 仍单进程；V0.11+ 再做）
- ⏸ V0.10 Workflow Runtime 完整实现（V0.9.4 后下一里程碑）

---

> V0.9.4 已 Accepted，可进入实施阶段。

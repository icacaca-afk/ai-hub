# ADR-0017: V0.9.4 — Execution Event + Metrics + Trace

- **状态**: Proposed（待 ChatGPT 审核）
- **日期**: 2026-07-17
- **里程碑**: V0.9.4
- **关联**: ADR-0008（Core Freeze）、ADR-0013（Planner 骨架）、ADR-0014（CLI + metadata 分层）、ADR-0015（LLM Planner + 语义）、ADR-0016（CLI --json + inspect + schema_version）
- **API Stability**: Experimental
- **ChatGPT 审核**: 待 V0.9.4 完成后发送
- **前序审核**: [V0.9.3 ChatGPT Review](../reviews/V0.9.3-chatgpt-review.md) — 9.98/10 APPROVED

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
@dataclass
class ExecutionEvent:
    type: str                        # event type (上述表格)
    timestamp: str                   # ISO 8601
    plan_id: str                     # 关联 Plan
    step_id: str | None = None       # 关联 Step（plan-level event 为 None）
    provider: str | None = None      # provider-level event 携带
    latency_ms: int | None = None    # timing event 携带
    data: dict[str, Any] = field(default_factory=dict)
```

### 决策 2：EventBus（事件分发）

**简单实现**（V0.9.4 不引入复杂总线）：

```python
# planner/event_bus.py（新增）
class EventBus:
    """进程内事件总线（单线程，订阅者同步回调）。

    V0.9.4 简单实现：list of callable subscribers。
    V0.9.5+ 持久化或并发场景时，可替换为 SQLite/Redis 持久化总线。
    """
    def __init__(self):
        self._subscribers: list[Callable[[ExecutionEvent], None]] = []

    def subscribe(self, handler: Callable[[ExecutionEvent], None]) -> None: ...
    def emit(self, event: ExecutionEvent) -> None: ...  # 同步回调
    def clear(self) -> None: ...  # 测试用
```

**为什么简单实现？**
- 单进程单线程（CLI 顺序调用），不需要 async
- 订阅者模式允许未来加 SQLite consumer / 内存 trace / 日志，无需改 emit 端
- ChatGPT：「SQLite / JSON / Memory 都只是 Consumer」

### 决策 3：ExecutionMetrics（与 ExecutionResult 解耦）

**ChatGPT 关键洞察**：

> 不要把 latency / token / cost 直接塞进 ExecutionResult。
> ExecutionResult 以后容易越来越胖。
> 建议单独 ExecutionMetrics { latency_ms / token_in / token_out / cost / retry }。

**新数据结构**：

```python
# planner/execution_metrics.py（新增）
@dataclass
class ExecutionMetrics:
    latency_ms: int = 0
    token_in: int = 0
    token_out: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0
    # 未来扩展
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
    区别：PlanStore 存 Plan（业务），TraceCollector 存 events（过程）。
    """
    def __init__(self, max_plans: int = 10):
        self._events: dict[str, list[ExecutionEvent]] = {}
        self._max = max_plans
        # 自动订阅
        self._bus: EventBus | None = None

    def attach(self, bus: EventBus) -> None:
        """订阅 EventBus。"""
        self._bus = bus
        bus.subscribe(self.handle)

    def handle(self, event: ExecutionEvent) -> None:
        """EventBus 回调：存到对应 plan_id 的 events 列表。"""
        ...

    def get_trace(self, plan_id: str) -> list[ExecutionEvent]: ...
    def list_traced_plans(self) -> list[str]: ...
```

**为什么独立于 PlanStore？** —— ChatGPT 建议：「PlanStore + ExecutionStore 职责不同」。V0.9.4 让两者解耦，为 V0.9.5+ 分裂做准备。

### 决策 8：ai-hub trace 命令

**新增 CLI**：

```
ai-hub trace <plan_id>           时间线（人类可读）
ai-hub trace <plan_id> --json    时间线 JSON
ai-hub trace --list              列出所有被 trace 的 plan_id
```

**时间线输出示例**（人类可读）：

```
AI Hub Trace — v0.9.4 (Current Process Only)

Plan: fake-plan-001
Task: task-fake-plan-001
Status: SUCCESS

Timeline (8 events, 0.5s total):
  0.0s  plan_started
  0.0s  planner_started (RuleBasedPlanner)
  0.0s  planner_finished (2 steps)
  0.1s  step_started [step-0: hello]
  0.1s  provider_selected (ScoreRouter → fake)
  0.3s  provider_finished (fake, 200ms)
  0.3s  step_finished [step-0: SUCCESS, 200ms]
  0.3s  step_started [step-1: world]
  ...
  0.5s  plan_finished (SUCCESS, 500ms)
```

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

### 决策 10：schema_version 升级

- `metadata.schema_version` 从 `"1"` → `"2"`
- 升级原因：metadata 加入 `aggregate_metrics`（Plan 层 metrics 聚合）+ `step.execution_metrics` 字段
- 老 consumer 读到 `"1"` 时应回退到「无 metrics」模式（不抛错）

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
10. `metadata.schema_version = "2"`（升级）
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

- **V0.9.5**：ExecutionStore（SQLite 持久化）+ 异步 EventBus
- **V0.9.6**：token / cost 自动采集（与 Provider 配合）
- **V0.10**：Workflow Runtime（条件分支 / 重试 / 暂停恢复 / DAG），内部仍用 EventBus 收集 trace

---

> 等待 ChatGPT 审核。建议提供完整 ADR + V0.9.3 review 上下文。

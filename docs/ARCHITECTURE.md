# AI Hub — Architecture Overview

> **版本**：v1.0.0（Draft，V1.0 启动前置）
> **状态**：Draft（待 ChatGPT 外部审核）
> **日期**：2026-07-17
> **重要性**：文档体系总入口
> **触发建议**：[Runtime Contract ChatGPT Review](reviews/runtime-contract-chatgpt-review.md) — ChatGPT Q7 建议在 V1.0 启动时增加 ARCHITECTURE.md

## 目的

为 AI Hub 项目提供**单一文档入口**。任何新加入的贡献者、用户、审核者，应该能通过本文档：

1. 在 5 分钟内理解 AI Hub 的整体架构
2. 找到所有重要文档（Runtime Contract / Provider Spec / ADR / Glossary）
3. 理解 Runtime 数据流（Task → ExecutionEvent → Store → Query）
4. 知道 V1.0 路线图

> ChatGPT Runtime Contract Q7 引言：
> "ARCHITECTURE.md 作为总入口，里面只放：Architecture Overview / Component Diagram / Document Map，然后跳转：Runtime Contract / Provider Spec / ADR / Glossary。这样文档体系会非常清晰。"

## 1. AI Hub 是什么

AI Hub 是一个 **AI Runtime**（不是简单的 AI Gateway 或 Provider Router）。

**核心定位**：

- **Task 第一公民**（不是 Provider 第一公民）
- **Event Sourcing 风格执行模型**（ExecutionEvent 是 Source of Truth）
- **Capability Routing**（不是 Provider Routing）
- **Workflow Runtime on ExecutionEvent**（V1.0 主题）

**与 OmniRoute / 类似项目的区别**：

| 维度 | AI Hub | OmniRoute / Gateway 类项目 |
|------|--------|--------------------------|
| 第一公民 | **Task** | Provider |
| 核心抽象 | **ExecutionEvent** | HTTP Request |
| 路由逻辑 | **Capability → Provider** | Provider → Model |
| 扩展点 | **Bridge**（HTTP / CLI / GUI / Browser / Future） | HTTP Endpoint |
| 可观察性 | **Event Stream + Statistics Projection** | Log + Metric |
| Workflow 支持 | **V1.0 on ExecutionEvent** | 无 |

> AI Hub 不与 OmniRoute 类项目竞争；可以将 OmniRoute 当作一个 Provider（`OmniRouteProvider`），通过 `APIBridge` 调用其 160+ Provider 聚合能力。详见 ADR-0025（V1.x 评估）。

## 2. 架构图

### 2.1 核心数据流（V0.9.7 现状）

```
                 ┌─────────────────────────────────────┐
                 │           Task                      │
                 │  (capabilities, input, priority)    │
                 └──────────────┬──────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────────┐
                │          Planner                  │
                │  (RuleBasedPlanner / LLMPlanner)  │
                └──────────────┬────────────────────┘
                               │ Plan (ordered Steps)
                               ▼
                ┌───────────────────────────────────┐
                │         PlanExecutor              │
                │  (orchestrates Step execution)    │
                └───┬─────────────────────────┬─────┘
                    │                         │
        ┌───────────▼──────────┐  ┌──────────▼──────────┐
        │  Capability Router   │  │      EventBus       │
        │  (ScoreRouter /      │  │  (synchronous fan-  │
        │   HealthRouter /     │  │   out)              │
        │   MetricsRouter)     │  └─┬─────────┬─────────┘
        └───────────┬──────────┘    │         │
                    │               │         │
                    ▼               ▼         ▼
        ┌────────────────────┐  ┌──────┐  ┌──────────────┐
        │  Provider + Bridge │  │ Trace│  │  SQLite      │
        │  (HTTP / CLI /     │  │ Col- │  │  Execution   │
        │   GUI / Browser)   │  │ lector│  │  Store       │
        └────────┬───────────┘  └──────┘  └──────┬───────┘
                 │                               │
                 │ BridgeResult                  │ query_events()
                 │ (output + raw)                │
                 ▼                               ▼
        ┌────────────────────┐        ┌────────────────────┐
        │  ExecutionEvent    │        │  Statistics        │
        │  (immutable fact)  │        │  Collector         │
        └────────────────────┘        │  (Read-Only        │
                                      │   Projection)      │
                                      └─────────┬──────────┘
                                                │
                                                ▼
                                      ┌────────────────────┐
                                      │  Execution         │
                                      │  Statistics        │
                                      │  + ai-hub stats    │
                                      └────────────────────┘
```

### 2.2 V1.0 路线（ExecutionPipeline on ExecutionEvent）

```
V0.9.7 现状                              V1.0 目标
─────────────                            ─────────────
Provider → Router (subclass)            Task → ExecutionPipeline (decorator)
             ↓                                       ↓
         PlanExecutor                          PlanExecutor
             ↓                                       ↓
         ExecutionEvent                        ExecutionEvent
```

**V1.0 关键变化**：

- 移除 MetricsRouter / HealthRouter 子类层级
- 引入 ExecutionPipeline 作为 Decorator / Middleware
- Router 重新变瘦（只负责 `route()`，不负责 `execute()` 装饰）

## 3. Component Overview

| 组件 | 路径 | 状态 | 职责 |
|------|------|------|------|
| **core/** | `core/*.py` | 冻结 (ADR-0008) | Provider / Bridge / Result / Task 接口 |
| **router/** | `router/*.py` | 部分冻结 | route() 选 Provider；execute() 装饰由 Pipeline 接管（V1.0） |
| **providers/** | `providers/*/` | 冻结 (ADR-0008) | 具体 Provider 实现（OpenAI / Gemini / Stub） |
| **planner/** | `planner/*.py` | Experimental | Plan 分解 + 验证 + Store + Executor + EventBus + Trace + SQLite + Statistics |
| **cli/** | `cli/*.py` | Experimental | CLI 入口（ask / plan / inspect / trace / history / stats） |
| **docs/** | `docs/*.md` | Accepted / Draft | 文档体系入口 |

## 4. 核心抽象

### 4.1 Task（第一公民）

```python
@dataclass
class Task:
    task_id: str
    input: str
    capabilities: list[str]   # 关键：能力优先于 Provider
    priority: int = 0
    metadata: dict = field(default_factory=dict)
```

**Task 由 Planner 分解为 Plan → Steps → 调用 Provider。**

### 4.2 ExecutionEvent（事实）

```python
@dataclass
class ExecutionEvent:
    event_id: str             # UUID 不可变
    type: str                 # plan_started / step_finished / provider_finished / ...
    plan_id: str
    timestamp: str            # ISO 8601
    step_id: str | None
    provider: str | None
    latency_ms: int | None
    data: dict[str, Any]      # JSON 可序列化，free-form
```

**ExecutionEvent 是 Source of Truth**（Runtime Contract 原则 A）。
**ExecutionEvent 不可变**（原则 B）。

### 4.3 Plan / Step（业务视图）

```python
@dataclass
class Step:
    step_id: str
    description: str
    required_capabilities: list[str]
    status: str              # 派生：pending / running / success / failed / skipped
    execution_metrics: ExecutionMetrics
```

**Step.status / ExecutionMetrics 都是 ExecutionEvent 派生视图**（非 Source of Truth）。

### 4.4 Provider + Bridge

```python
class Provider(ABC):
    name: str
    capabilities: list[str]
    def select_bridge(self, task: Task) -> Bridge: ...
    def quota_left(self) -> int: ...

class Bridge(ABC):
    def run(self, task: Task) -> BridgeResult: ...
```

**Provider 不可执行 execute()**（见 PROVIDER_SPEC.md）。
**Bridge 是 Provider 与 Runtime 的唯一接口**（HTTP / CLI / GUI / Browser 通用）。

### 4.5 EventBus（解耦 Consumer）

```python
class EventBus:
    def subscribe(self, event_type: str | None, handler: Callable) -> None: ...
    def unsubscribe(self, handler: Callable) -> None: ...
    def emit(self, event: ExecutionEvent) -> None: ...
```

**EventBus 是同步广播**：所有 Consumer 按订阅顺序串行调用，Consumer 失败必须内部消化（Runtime Contract Q2）。

## 5. 数据流（Runtime Observability）

### 5.1 写入路径

```
PlanExecutor
    │
    ├─ _emit_event("plan_started", ...)
    ├─ _emit_event("step_started", ...)
    ├─ _emit_event("provider_selected", ...)
    ├─ _emit_event("provider_finished", data={"server_metrics": ...})
    ├─ _emit_event("step_finished", ...)
    └─ _emit_event("plan_finished", ...)
              │
              ▼
         EventBus (synchronous)
              │
              ├─────► InMemoryTraceCollector (Memory, 进程级)
              │
              └─────► SQLiteExecutionStore (持久化, 跨进程)
```

### 5.2 读取路径（V0.9.7 之后）

```
CLI (ai-hub history / stats / inspect)
    │
    ▼
SQLiteExecutionStore.query_events(...)
    │  (canonical query interface)
    │
    ├─ history → list_plans / get_events (Convenience API)
    │
    └─ stats → StatisticsCollector.compute(events)
                  │
                  ▼
              ExecutionStatistics
              (Read-Only Projection)
```

**所有 CLI / Dashboard / API 都基于 `query_events()`**（Runtime Contract 4.1）。

## 6. Core Freeze 边界

**永远只读**（ADR-0008）：

- `core/` — Provider / Bridge / Result / Task 接口
- `router/router.py` — Router 基类（子类化扩展，不修改基类）
- `providers/` — 具体 Provider 实现

**可修改**：

- `router/*.py`（除 router.py）— Router 子类（V1.0 前）
- `planner/` — 所有 Planner / Executor / EventBus / Storage / Statistics
- `cli/` — 所有 CLI 命令
- `docs/` — 所有文档

**V0.9.6 临时层**：

- `router/metrics_router.py` — 解决 Core Freeze 下加 server_metrics，V1.0 退出（见 Runtime Contract 8）

## 7. 文档体系

```
ARCHITECTURE.md（本文件，V1.0 新增）
│
├── Architecture Overview  ← §1-6
│
├── Component Overview     ← §3
│
└── Document Map           ← §7（本文）
    │
    ├── Runtime Contract   → 运行时行为约定（Accepted, 10.0/10）
    │
    ├── PROVIDER_SPEC.md   → Provider 实现规范
    │
    ├── docs/adr/          → 历史决策记录
    │   ├── ADR-0008 (Core Freeze)
    │   ├── ADR-0017 (Execution Event)
    │   ├── ADR-0018 (SQLiteExecutionStore)
    │   ├── ADR-0019 (Provider Metrics)
    │   └── ADR-0020 (Execution Analytics)
    │
    ├── docs/reviews/      → ChatGPT 外部审核记录
    │
    └── Glossary           → V1.0 评估（ChatGPT Q7 建议）
```

## 8. V1.0 路线图

按 ChatGPT Runtime Contract Q8 建议"按阶段写 ADR"：

| 阶段 | ADR | 主题 | 状态 |
|------|-----|------|------|
| V1.0.0 | **ARCHITECTURE.md**（本文件） | 文档体系入口 | Draft → 待审核 |
| V1.0.1 | ADR-0021 | ExecutionPipeline（Decorator 替代 Router 子类） | Planned |
| V1.0.2 | ADR-0022 | Retry Policy（Failure-Driven Retry on ExecutionEvent） | Planned |
| V1.0.3 | ADR-0023 | Checkpoint / Resume（基于 ExecutionEvent 流回放） | Planned |
| V1.0.4 | ADR-0024 | Condition / Branching（事件驱条件分支） | Planned |
| V1.x | ADR-0025 | OmniRouteProvider（V1.x 扩展，融合方案） | Planned |

**节奏**：

```
ADR (Proposed) → ChatGPT 审核 → 编码 → 测试 → ChatGPT 代码审核 → 冻结 → 下一 ADR
```

不一口气写整个 Workflow Runtime 3000 行 ADR（ChatGPT Runtime Contract Q8 明确建议）。

## 9. V0.9.x 收官总结

| 版本 | 主题 | ADR 评分 | 代码/Contract 评分 |
|------|------|---------|-----------------|
| V0.9.0~V0.9.2 | Planner Skeleton → LLM Planner | 9.5/10 | — |
| V0.9.3 | Inspect / PlanStore | 9.98/10 | — |
| V0.9.4 | ExecutionEvent / Trace | 10.0/10 | 10.0/10 |
| V0.9.5 | SQLiteExecutionStore | 10.0/10 | 10.0/10 |
| V0.9.6 | Provider Metrics | 9.95/10 | 10.0/10 (Final) |
| V0.9.7 | Execution Analytics | 9.95/10 | 10.0/10 (Final) |
| **Runtime Contract** | **运行时约定** | — | **10.0/10 (Final)** |
| **ARCHITECTURE.md** | **文档体系入口** | — | **Draft（待审核）** |

**V0.9.x Runtime Observability 阶段 + 运行时约定层 + 文档体系入口全部就绪。**

V1.0 Workflow Runtime 启动前置条件已满足。

## 10. 后续

- 本文档（ARCHITECTURE.md）完成后发 ChatGPT 外部审核
- 通过后作为 V1.0 正式基线文档
- 后续 V1.0.1~V1.0.4 每个新能力单独 ADR
- 文档体系如有扩展（Glossary / Workflow Contract）单独走 ADR 流程

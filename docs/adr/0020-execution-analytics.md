# ADR-0020: V0.9.7 — Execution Analytics（query_events + Statistics）

- **状态**: Accepted（ChatGPT 外部审核 9.95/10 APPROVED）
- **日期**: 2026-07-17
- **里程碑**: V0.9.7
- **关联**: ADR-0008（Core Freeze）、ADR-0017（Execution Event）、ADR-0018（SQLiteExecutionStore + 原则 C: Event Query 统一）、ADR-0019（Provider Metrics）
- **API Stability**: Experimental
- **ChatGPT 审核**: 9.95/10 APPROVED（2026-07-17）
- **前序审核**: [V0.9.6 代码 ChatGPT Review](../reviews/V0.9.6-code-chatgpt-review.md) — 10.0/10 APPROVED (Final)
- **本版审核**: [V0.9.7 ADR ChatGPT Review](../reviews/V0.9.7-adr-chatgpt-review.md) — 9.95/10 APPROVED

## 背景

V0.9.6 ChatGPT Final 审核明确建议：

> **下一步：V0.9.7 Statistics（Execution Analytics）**
>
> 主题：`query_events(...)` 作为 SQLiteExecutionStore 真正的公共接口。
> 所有 CLI（trace / inspect / exec-history / stats）基于 `query_events()` 而不是每个自己写 SQL。
>
> 然后再增加 Statistics：
> ```
> ai-hub stats
> ```
> 输出：Plans / Steps / Providers / Average Latency / Total Tokens / Estimated Cost / Failure Rate
>
> 这些全部来自 `query_events()`，而不是 Plan。

ADR-0018 原则 C 已预留此方向：

> **原则 C：Event Query 统一（V0.9.7+ 方向）**
> 所有 Query 围绕 Event（`query_events(...)`），不要 `get_plan(...)`。
> History / Timeline / Statistics 全部由 Event 派生。
> ExecutionStore 始终只是 Event Store，**不会慢慢演变成 Workflow DB**。

### 当前状态（V0.9.6 收官后）

```
Plan → Execute → ExecutionEvent → ExecutionMetrics → Memory Trace → SQLite History
                                       ↓                    ↓               ↓
                                  (token/cost)       ai-hub trace    ai-hub exec-history
```

**问题**：
1. **查询接口分散**：`SQLiteExecutionStore` 有 `get_events(plan_id)` / `list_plans()` / `has()` 三个方法，各自写 SQL，无法统一过滤
2. **CLI 各自写 SQL**：`cli/history.py` 直接调 `store.list_plans()` / `store.get_events()`，未来 `stats` 命令又要写新 SQL
3. **没有聚合层**：用户无法快速看"最近成功率多少 / 平均延迟多少 / 总花了多少钱"
4. **ExecutionMetrics 数据未被消费**：V0.9.6 已采集 token/cost，但没有查询入口

## 目标

1. **`query_events(...)` 统一查询接口**：SQLiteExecutionStore 暴露单一查询入口，支持多维过滤
2. **CLI 重构**：`exec-history` 基于 `query_events()`，不再直接写 SQL
3. **`ai-hub stats` 命令**：聚合统计（成功率 / 平均延迟 / token 总量 / 估算成本 / 失败率）
4. **落地 ADR-0018 原则 C**：Event Query 统一，ExecutionStore 不会演变成 Workflow DB

**约束**：
- ❌ 不改 core/ + router/ + providers/（Core Freeze 延续）
- ❌ 不改 `ExecutionEvent` / `EventBus` / `ExecutionMetrics` 数据结构
- ✅ 可改 `planner/sqlite_execution_store.py`（新增 `query_events()`，保留旧接口向后兼容）
- ✅ 可改 `cli/history.py`（重构为 `query_events()`）
- ✅ 可新增 `cli/stats.py` + `planner/statistics.py`

## 决策

### 决策 1：`query_events(...)` 统一查询接口

**新增** `SQLiteExecutionStore.query_events()`：

```python
def query_events(
    self,
    plan_id: str | None = None,
    event_type: str | None = None,
    provider: str | list[str] | None = None,   # ChatGPT Q7: 支持单/多 provider
    step_id: str | None = None,
    since: str | None = None,        # ISO 8601 timestamp
    until: str | None = None,        # ISO 8601 timestamp
    limit: int | None = None,        # None = 不限
) -> list[ExecutionEvent]:
    """统一查询接口（ADR-0018 原则 C 落地）。

    所有参数 Optional，组合过滤。返回 list[ExecutionEvent]（按 timestamp 升序）。

    ChatGPT Q7 调整：provider 参数支持 str | list[str] | None。
    - CLI 当前仍只传单 provider（`--provider openai_api`）
    - 但接口已为未来 API 场景（`provider=["a", "b"]`）预留
    - CLI 不用变，接口已经准备好了

    Examples:
        query_events(plan_id="plan-abc")              # 某 plan 的全部 events
        query_events(event_type="provider_finished")  # 所有 provider_finished
        query_events(provider="openai_api")           # 单 provider
        query_events(provider=["openai_api", "openai_compatible"])  # 多 provider (ChatGPT Q7)
        query_events(since="2026-07-17T00:00:00Z")    # 某时刻之后
        query_events(plan_id="plan-abc", event_type="step_finished")  # 组合过滤
    """
```

**实现**：动态构建 WHERE 子句 + 参数列表（provider 支持 IN 子句）：

```python
def query_events(self, plan_id=None, event_type=None, provider=None,
                 step_id=None, since=None, until=None, limit=None):
    clauses = []
    params = []
    if plan_id is not None:
        clauses.append("plan_id = ?"); params.append(plan_id)
    if event_type is not None:
        clauses.append("type = ?"); params.append(event_type)
    if provider is not None:
        # ChatGPT Q7: 支持 str | list[str]
        if isinstance(provider, str):
            clauses.append("provider = ?"); params.append(provider)
        else:
            # list[str] → IN (?, ?, ...)
            placeholders = ", ".join("?" * len(provider))
            clauses.append(f"provider IN ({placeholders})")
            params.extend(provider)
    if step_id is not None:
        clauses.append("step_id = ?"); params.append(step_id)
    if since is not None:
        clauses.append("timestamp >= ?"); params.append(since)
    if until is not None:
        clauses.append("timestamp <= ?"); params.append(until)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (f"SELECT event_id, type, plan_id, timestamp, step_id, provider, "
           f"latency_ms, data FROM execution_events{where} "
           f"ORDER BY timestamp ASC")
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    rows = self._conn.execute(sql, params).fetchall()
    return [self._row_to_event(r) for r in rows]
```

**为什么不引入 QueryBuilder / DSL？**（ChatGPT Q1 完全赞同）
- 当前查询复杂度只有 AND，没有 OR / NOT / GROUP / HAVING / ORDER BY / JOIN
- DSL 没有任何收益
- ChatGPT 明确："现在会明显过度设计"
- 等 V1.x 真出现 `(provider=A OR provider=B) AND latency>1000 AND status=failed` 再设计 QueryBuilder

### 决策 2：旧接口保留（向后兼容）+ Convenience API 标注

**保留** `get_events(plan_id)` / `list_plans(limit)` / `has(plan_id)`：

```python
def get_events(self, plan_id: str) -> list[ExecutionEvent]:
    """向后兼容：等价于 query_events(plan_id=plan_id)。"""
    return self.query_events(plan_id=plan_id)

def has(self, plan_id: str) -> bool:
    """是否有该 plan_id 的 event。"""
    # 保留原实现（单条 SQL EXISTS 更高效，不需要拉全部 events）
    ...
```

**ChatGPT Q2 建议明确**：`list_plans()` 是 **Convenience API, implemented via query_events()**。

文档必须写清楚：`query_events()` 和 `list_plans()` 不是两套查询系统，`list_plans()` 只是 `query_events(event_type="plan_started")` 的 helper。

**为什么保留？**
- 现有测试 / CLI 代码不破坏
- `list_plans()` 作为便利方法保留，但内部基于 `query_events()` 派生（落地原则 C）
- `has()` 是 EXISTS 探针，比 `query_events()` 拉 events 更高效（单条 SQL）

**`list_plans()` 重构**：内部改用 `query_events(event_type="plan_started")` 派生 plan 列表（落地原则 C），但对外接口不变。

```python
def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
    """Convenience API：列出最近 N 个 plan execution。

    内部基于 query_events(event_type="plan_started") 派生（ChatGPT Q2 明确）。
    不是独立查询系统，是 query_events() 的 helper。
    """
    plan_started_events = self.query_events(event_type="plan_started", limit=limit)
    # 从 plan_started events 派生 plan 列表（含 started/finished/event_count/status/step_count）
    ...
```

### 决策 3：`ai-hub stats` 命令

**新增** `cli/stats.py` + `planner/statistics.py`：

```
ai-hub stats                          全局统计（全部 plans）
ai-hub stats --plan <plan_id>         某 plan 的统计
ai-hub stats --provider <name>        某 provider 的统计
ai-hub stats --since <iso> --until <iso>  时间范围
ai-hub stats --json                   JSON 输出
```

**默认人类可读输出**：

```
AI Hub Statistics — v0.9.7 (SQLite: ./.ai-hub/execution.db)

Time Range: 2026-07-15 09:00 ~ 2026-07-17 18:00

Plans: 42 total
  Success: 38 (90.5%)
  Failed: 4 (9.5%)

Steps: 87 total
Events: 524 total

Providers:
  openai_api           35 calls  avg 450ms  12.5K tokens in  8.2K tokens out  est. $0.42
  openai_compatible     7 calls  avg 380ms   2.1K tokens in  1.5K tokens out  est. $0.08

Average Plan Latency: 1.2s
Average Step Latency: 380ms

Total Estimated Cost: $0.50
```

**JSON 输出**：

```json
{
  "version": "0.9.7",
  "source": "sqlite",
  "db_path": "./.ai-hub/execution.db",
  "time_range": {"since": "...", "until": "..."},
  "plans": {"total": 42, "success": 38, "failed": 4, "success_rate": 0.905},
  "steps": {"total": 87},
  "events": {"total": 524},
  "providers": [
    {
      "name": "openai_api",
      "calls": 35,
      "avg_latency_ms": 450,
      "token_in": 12500,
      "token_out": 8200,
      "cost_usd": 0.42
    }
  ],
  "latency": {"avg_plan_ms": 1200, "avg_step_ms": 380},
  "total_cost_usd": 0.50
}
```

### 决策 4：`ExecutionStatistics` 数据结构

**新增** `planner/statistics.py`：

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ProviderStatistics:
    """单 Provider 的聚合统计。"""
    name: str
    calls: int = 0
    success_count: int = 0
    failed_count: int = 0
    avg_latency_ms: float = 0.0
    total_token_in: int = 0
    total_token_out: int = 0
    total_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class ExecutionStatistics:
    """全局执行统计（从 ExecutionEvent 派生）。"""
    # 时间范围
    since: str | None = None
    until: str | None = None
    # Plan 维度
    plan_total: int = 0
    plan_success: int = 0
    plan_failed: int = 0
    # Step 维度
    step_total: int = 0
    # Event 维度
    event_total: int = 0
    # Provider 维度
    providers: list[ProviderStatistics] = field(default_factory=list)
    # Latency
    avg_plan_latency_ms: float = 0.0
    avg_step_latency_ms: float = 0.0
    # Cost
    total_cost_usd: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.plan_total == 0:
            return 0.0
        return self.plan_success / self.plan_total

    def to_dict(self) -> dict[str, Any]: ...
```

**为什么是 dataclass 而不是 dict？**
- 类型安全 / IDE 补全
- 与 `ExecutionMetrics` / `ExecutionEvent` 一致（都是 dataclass）
- `to_dict()` 支持 JSON 序列化

### 决策 5：`StatisticsCollector`（从 events 派生统计）— Read-Only Projection

**新增** `planner/statistics.py` 内的 `StatisticsCollector`：

```python
class StatisticsCollector:
    """从 ExecutionEvent 列表派生 ExecutionStatistics。

    纯计算类，不接触 SQLite / EventBus。
    输入：list[ExecutionEvent]（来自 query_events()）
    输出：ExecutionStatistics

    ⚠️ ChatGPT 唯一建议补充的原则（0.05 分）：
    StatisticsCollector MUST be a pure read-only projection.
    - 绝不修改 ExecutionEvent
    - 绝不补 ExecutionEvent
    - 绝不缓存 ExecutionEvent
    - 绝不写回 SQLite
    这是 Event Sourcing 的重要原则：Analytics Never Mutates Events。
    """

    @staticmethod
    def compute(events: list[ExecutionEvent]) -> ExecutionStatistics:
        """从 events 派生统计（Pure Read-Only Projection）。

        识别的 event 类型：
        - plan_started / plan_finished → plan_total / success / failed
        - step_started / step_finished → step_total
        - provider_finished → provider stats（latency / token / cost）

        本方法无副作用：
        - 不修改入参 events
        - 不接触任何 Store / EventBus
        - 不缓存
        - 不写回
        """
        stats = ExecutionStatistics()
        # ... 单次遍历 events，按 type 分发累积（只读访问）...
        return stats
```

**为什么独立类而不是 SQLiteExecutionStore 方法？**
- 单一职责：SQLiteExecutionStore 负责"存 + 查"，StatisticsCollector 负责"算"
- 可测试性：纯函数式计算，不需要 DB fixture
- 未来可复用：TraceCollector 的内存 events 也能用同一个 collector
- **Read-Only Projection 原则**（ChatGPT 唯一补充建议）：
  - StatisticsCollector 是 Event Sourcing 中的 Projection
  - Event 是 Source of Truth，Statistics 是派生视图
  - 派生视图绝不能反向修改 Source
  - 否则 Analytics 会慢慢污染 Storage，破坏 Event 不可变性

**ChatGPT 引言**：
> Analytics Never Mutates Events
> StatisticsCollector MUST be a pure read-only projection.
> 这是 Event Sourcing 很重要的一条原则。

### 决策 6：`cli/history.py` 重构（基于 query_events）

**修改前**（V0.9.6）：

```python
def _list_executions(json_output, limit):
    store = get_execution_store()
    executions = store.list_plans(limit=limit)  # 直接调 list_plans
    ...

def _show_timeline(plan_id, json_output):
    store = get_execution_store()
    events = store.get_events(plan_id)  # 直接调 get_events
    ...
```

**修改后**（V0.9.7）：

```python
def _list_executions(json_output, limit):
    store = get_execution_store()
    # 通过 query_events 拿 plan_started events，再派生 plan 列表
    plan_started_events = store.query_events(event_type="plan_started", limit=limit)
    # ... 从 events 派生 plan 列表（或保留调用 list_plans，但 list_plans 内部改用 query_events）
    executions = store.list_plans(limit=limit)  # list_plans 内部重构为基于 query_events
    ...

def _show_timeline(plan_id, json_output):
    store = get_execution_store()
    events = store.query_events(plan_id=plan_id)  # 统一接口
    ...
```

**重构原则**：
- `cli/history.py` 只调 `query_events()`，不直接写 SQL
- `list_plans()` 作为 SQLiteExecutionStore 的便利方法保留，但内部重构为基于 `query_events(event_type="plan_started")`
- `get_events(plan_id)` 作为 `query_events(plan_id=plan_id)` 的别名保留

### 决策 7：`cli/trace.py` 不重构

**不修改** `cli/trace.py`：

**原因**：
- `trace` 命令查 `InMemoryTraceCollector`（内存，进程级），不是 SQLite
- `InMemoryTraceCollector` 已有自己的查询接口（`get_events(plan_id)` / `get_all_events()`）
- 给 `InMemoryTraceCollector` 也加 `query_events()` 会扩大 V0.9.7 范围
- ChatGPT 提到 trace 应该基于 query_events，但内存和 SQLite 是两个数据源，统一接口可推迟

**V0.9.7 决策**：`trace` 保持现状，V1.0 再评估是否给 `InMemoryTraceCollector` 加 `query_events()` 统一接口。

**`inspect` 命令**：基于 `PlanStore`（业务视图），不是 Event 视图，V0.9.7 不重构。

### 决策 8：`ai-hub stats` 派生全部从 events

**关键约束**（ChatGPT 建议）：

> 这些全部来自 `query_events()`，而不是 Plan。

**实施**：
- `ai-hub stats` 调 `query_events()` 拿全部 events（或按过滤条件）
- 调 `StatisticsCollector.compute(events)` 派生 `ExecutionStatistics`
- 输出人类可读 / JSON

**不调 PlanStore**：
- PlanStore 是业务视图（Plan / Step / Task），不是执行视图
- Statistics 是执行统计，应从 ExecutionEvent 派生
- 印证 ADR-0018 原则 C：所有 Query 围绕 Event

### 决策 9：Core Freeze 维持

- core/ + router/ + providers/ 0 修改
- V0.9.7 全部新增 / 修改在 `planner/` + `cli/`
- `SQLiteExecutionStore` 是 planner 内部组件，扩展查询接口不影响 Core

### 决策 10：schema_version 维持 "1"

**Postel's Law 延续**：
- V0.9.7 不改变 SQLite schema（不新增列 / 不新增表）
- `query_events()` 是查询接口，不改存储格式
- `ai-hub stats --json` 是新命令，新输出 schema，不影响现有
- `metadata.schema_version` 维持 "1"

## 架构

```
┌─────────────────────┐
│ PlanExecutor        │
│   emit("...")       │──→ EventBus ──→ InMemoryTraceCollector (V0.9.4)
│                     │         │           │
└─────────────────────┘         │           ↓
                                │       ai-hub trace (进程级 Timeline)
                                │
                                ↓
                    SQLiteExecutionStore (V0.9.5)
                                │
                                │ V0.9.7 新增统一查询接口
                                ↓
                        query_events(...)
                                │
                    ┌───────────┼───────────┐
                    ↓           ↓           ↓
              ai-hub        ai-hub       ai-hub
              exec-history  stats        (future)
                    │           │
                    ↓           ↓
              list plans    ExecutionStatistics
              show timeline  (success rate / latency / cost)
```

**关键演进**：
- V0.9.5：SQLiteExecutionStore 持久化（`get_events` / `list_plans` / `has`）
- V0.9.7：统一查询接口（`query_events`）+ 聚合统计（`ExecutionStatistics`）
- 未来：所有 CLI 基于 `query_events()`，不再各自写 SQL

## 范围

### 只做

1. `planner/sqlite_execution_store.py`（修改）— 新增 `query_events()`，重构 `list_plans()` 内部基于 `query_events()`
2. `planner/statistics.py`（新增）— `ExecutionStatistics` + `ProviderStatistics` + `StatisticsCollector`
3. `cli/stats.py`（新增）— `ai-hub stats` 命令
4. `cli/main.py`（修改）— 注册 stats 命令
5. `cli/history.py`（修改）— 重构为 `query_events()`（保留对外行为不变）
6. `planner/__init__.py`（修改）— 导出 `ExecutionStatistics` / `StatisticsCollector`
7. 完整测试

### 不做（V0.9.8+ / V1.0+ 推迟）

- ❌ 修改 `InMemoryTraceCollector`（V1.0 再统一接口）
- ❌ 修改 `cli/trace.py`（V1.0 再重构）
- ❌ 修改 `cli/inspect.py`（基于 PlanStore，不属 Event 视图）
- ❌ QueryBuilder / DSL（V1.0+ 复杂查询需求时再引入）
- ❌ 修改 core/ + router/ + providers/
- ❌ Decimal 替代 float（V1.0 评估，ChatGPT V0.9.6 Q8 建议）
- ❌ 时间序列统计（按小时 / 按天分组，V0.9.8+）
- ❌ P95 / P99 latency（V0.9.8+，当前只算 avg）
- ❌ Export / Import（V0.9.8+）

## 测试策略

测试覆盖：
- `test_sqlite_execution_store.py`（更新）— `query_events()` 多维过滤
  - 单维度过滤（plan_id / event_type / provider / step_id / since / until）
  - 组合过滤
  - limit 参数
  - 空结果
  - 与 `get_events()` / `list_plans()` 一致性验证
- `test_statistics.py`（新增）— `StatisticsCollector` + `ExecutionStatistics`
  - 空 events → 全 0
  - 单 plan 全成功
  - 单 plan 失败
  - 多 plan 混合
  - 多 provider 聚合
  - token / cost 累加
  - success_rate 计算
  - to_dict() 序列化
- `test_cli_stats.py`（新增）— `ai-hub stats` 命令
  - 空数据库
  - 全局统计
  - --plan <plan_id>
  - --provider <name>
  - --since / --until
  - --json 输出
  - 子进程调用
- `test_cli_exec_history.py`（更新）— 行为不变，验证重构无回归
- `test_cli_plan.py` / `test_cli_plan_json.py`（更新）— version 0.9.6 → 0.9.7

**测试隔离**：每个测试用 `tmp_path` 创建临时 DB 文件，不污染 `./.ai-hub/execution.db`。

目标：测试基线 449 → 490+ passed。

## 兼容性

- `SQLiteExecutionStore` 旧接口（`get_events` / `list_plans` / `has`）保留，向后兼容
- `cli/history.py` 对外行为不变（重构内部实现）
- `metadata.schema_version` 维持 "1"
- 新增 `ai-hub stats` 命令（不影响现有命令）
- SQLite schema 不变（不新增列 / 不新增表）

## 风险

| 风险 | 缓解 |
|------|------|
| `query_events()` SQL 拼接注入 | 参数化查询（`?` 占位符），不接受字符串拼接 SQL |
| `list_plans()` 重构后性能 | `query_events(event_type="plan_started")` 走 type 索引，性能与原 GROUP BY 相当 |
| 大量 events 时 stats 慢 | V0.9.7 单进程 CLI，events 数 <10K；V1.0+ 加物化视图或缓存 |
| Statistics 计算错误 | 单元测试覆盖多种场景（空 / 单 plan / 多 plan / 失败混合） |
| 旧测试破坏 | `get_events` / `list_plans` / `has` 保留向后兼容 |

## 确认问题（发 ChatGPT 审核）

1. **`query_events()` 接口设计**：6 个 Optional 过滤参数（plan_id / event_type / provider / step_id / since / until）+ limit，是否足够？还是应该引入 QueryBuilder / dataclass 参数？
2. **`list_plans()` 重构**：内部改用 `query_events(event_type="plan_started")` 派生 plan 列表，对外接口不变。是否合理？还是应该直接废弃 `list_plans()` 让 CLI 自己派生？
3. **`StatisticsCollector` 独立类**：纯计算类，不接触 SQLite / EventBus，输入 list[ExecutionEvent] 输出 ExecutionStatistics。是否合理？还是应该作为 SQLiteExecutionStore 的方法？
4. **`trace` 不重构**：V0.9.7 只重构 SQLite-backed CLI（exec-history / stats），不重构 trace（内存）。是否合理？还是应该 V0.9.7 一起统一？
5. **stats 不算 P95 / P99**：V0.9.7 只算 avg latency，P95 / P99 推迟 V0.9.8+。是否太保守？
6. **`ExecutionStatistics` 用 float**：cost_usd 仍用 float（延续 V0.9.6），V1.0 再评估 Decimal。是否可接受？
7. **`ai-hub stats --provider`**：按 provider 聚合时，是否应该支持多个 provider 组合查询？还是单 provider 即可？
8. **V0.9.7 范围克制**：不做 QueryBuilder / 时间序列 / P95 / Decimal / trace 重构，只做 query_events + stats + history 重构。是否太保守或正好？

## 后续路线

```
V0.9.7  Execution Analytics（本版本）— query_events + Statistics
  ↓
V0.9.8  Advanced Statistics（时间序列 / P95 / P99 / Decimal）— 可选
  ↓
V1.0    Workflow Runtime on ExecutionEvent（Condition / Retry / Checkpoint / Resume 都是 ExecutionEvent）
```

**额外建议**（ChatGPT V0.9.6 Final 提出，比功能更重要）：

> **Runtime Contract**
>
> 新增 `docs/runtime-contract.md`，明确：
> - ExecutionEvent 生命周期
> - ExecutionMetrics 定义
> - server_metrics vs ExecutionMetrics 的区别
> - EventBus / Consumer / Storage 保证
> - Postel's Law
>
> 重要性已经和 Provider Contract 一样高。

**V0.9.7 落地**：本 ADR 不直接写 Runtime Contract，但 V0.9.7 完成后可单独写 `docs/runtime-contract.md`（不阻塞 V0.9.7 代码）。

---

> V0.9.7 ADR Accepted（ChatGPT 外部审核 9.95/10 APPROVED）。
> 采纳 2 项调整（provider list[str] + list_plans Convenience API 标注）+ 1 条原则（Read-Only Projection）。
> 进入实施阶段。

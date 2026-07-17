# ADR-0018: V0.9.5 — SQLiteExecutionStore（Execution Event 持久化）

- **状态**: Proposed
- **日期**: 2026-07-17
- **里程碑**: V0.9.5
- **关联**: ADR-0008（Core Freeze）、ADR-0017（Execution Event + Metrics + Trace）
- **API Stability**: Experimental
- **前序审核**: [V0.9.4 代码 ChatGPT Review](../reviews/V0.9.4-code-chatgpt-review.md) — 10.0/10 APPROVED

## ⚠️ 核心设计原则（继承 ADR-0017）

> **SQLiteExecutionStore 是 EventBus 的独立 Consumer，不是 TraceCollector 的子类。**
>
> ```
> ExecutionEvent → TraceCollector → Timeline（内存，进程级）
> ExecutionEvent → SQLiteExecutionStore → DB（持久化，跨进程生命）
> ```
>
> ChatGPT V0.9.4 代码审核明确建议：
> - SQLite 是 Storage，不是 Trace
> - 两者都是 EventBus Consumer，互不继承，互不引用
> - 只有 CLI 负责组合（CLI → SQLiteExecutionStore + TraceCollector）

## 背景

V0.9.4 完成了 Execution Event 模型 + EventBus + InMemoryTraceCollector。ChatGPT 代码审核 10.0/10 APPROVED，并明确建议 V0.9.5 走**方案 A**：

> A: Memory → SQLite Consumer ★★★★★ 最推荐
>
> 甚至 ExecutionStore 不要继承 TraceCollector，而是两者都是 EventBus Consumer。
> 不要 SQLiteTraceCollector，因为 SQLite 不是 Trace，SQLite 只是 Storage。

V0.9.4 的 InMemoryTraceCollector 是进程级的——进程退出即丢失。用户无法查看"上一次执行"的 trace。V0.9.5 引入 SQLiteExecutionStore，把 ExecutionEvent 持久化到本地 SQLite 文件，跨进程生命。

## 目标

把 ExecutionEvent 从"进程内存"推进到"本地持久化"，让用户能查看历史执行记录，同时不侵入 Executor、不污染 TraceCollector。

## 决策

### 决策 1：SQLiteExecutionStore 作为独立 EventBus Consumer

**ChatGPT 核心建议**：

> ExecutionStore 不要继承 TraceCollector，而是两者都是 EventBus Consumer。

**实现**：

```python
# planner/sqlite_execution_store.py（新增）
class SQLiteExecutionStore:
    """SQLite 持久化 ExecutionEvent（EventBus Consumer）。

    与 TraceCollector 完全独立：
    - TraceCollector：内存，进程级，环形缓冲，Timeline 视图
    - SQLiteExecutionStore：SQLite，持久化，跨进程生命，历史查询

    两者都订阅 EventBus，互不引用。
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._init_db()
        self._bus: EventBus | None = None
        self._handle_bound = self.handle  # 预绑定（同 TraceCollector 模式）

    def attach(self, bus: EventBus) -> None:
        if self._bus is not None:
            self.detach()
        self._bus = bus
        bus.subscribe(None, self._handle_bound)

    def detach(self) -> None:
        if self._bus is not None:
            self._bus.unsubscribe(self._handle_bound)
            self._bus = None

    def handle(self, event: ExecutionEvent) -> None:
        """EventBus 回调：INSERT 到 SQLite。"""
        # V0.9.5 同步 INSERT（单进程 CLI，数据量小，<1ms per INSERT）
        ...

    def get_events(self, plan_id: str) -> list[ExecutionEvent]: ...
    def list_plans(self, limit: int = 20) -> list[dict]: ...
    def has(self, plan_id: str) -> bool: ...
    def close(self) -> None: ...
```

**为什么不继承 TraceCollector？**
- 职责不同：TraceCollector 回答"怎么发生的？"（Timeline），SQLiteExecutionStore 回答"以前发生过什么？"（History）
- 生命周期不同：TraceCollector 进程级，SQLiteExecutionStore 跨进程
- ChatGPT："SQLite 不是 Trace，SQLite 只是 Storage"

### 决策 2：SQLite Schema

**单表设计**（events 表）：

```sql
CREATE TABLE IF NOT EXISTS execution_events (
    event_id   TEXT PRIMARY KEY,        -- ExecutionEvent.event_id (UUID hex)
    type       TEXT NOT NULL,           -- plan_started / step_finished / ...
    plan_id    TEXT NOT NULL,           -- 关联 Plan
    timestamp  TEXT NOT NULL,           -- ISO 8601
    step_id    TEXT,                    -- 关联 Step（plan-level event 为 NULL）
    provider   TEXT,                    -- provider-level event 携带
    latency_ms INTEGER,                 -- Provider latency（显式记录）
    data       TEXT                     -- JSON 序列化的 event.data
);

CREATE INDEX IF NOT EXISTS idx_events_plan_id   ON execution_events(plan_id);
CREATE INDEX IF NOT EXISTS idx_events_type      ON execution_events(type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON execution_events(timestamp);
```

**为什么单表？**
- ExecutionEvent 是扁平的，不需要规范化
- data 字段用 JSON 存储灵活字段（未来加字段不用 ALTER TABLE）
- 查询模式简单：by plan_id / by type / by timestamp

**为什么不需要 plans 表？**
- Plan 信息从 events 派生（plan_started + plan_finished）
- 避免双写一致性问题（Plan 在 PlanStore，events 在 SQLite）
- ChatGPT D5 已明确：PlanStore 和 ExecutionStore 职责不同，不统一

### 决策 3：DB 文件位置

**默认路径**：`~/.ai-hub/execution.db`

**可配置**：环境变量 `AI_HUB_DB_PATH` 覆盖默认路径。

```python
DEFAULT_DB_PATH = Path.home() / ".ai-hub" / "execution.db"

def _resolve_db_path(custom: str | None = None) -> Path:
    if custom:
        return Path(custom)
    env = os.environ.get("AI_HUB_DB_PATH")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH
```

**为什么放用户目录？**
- 跨项目共享（用户可能在多个项目用 ai-hub）
- 不污染项目目录（项目 .gitignore 不用改）
- 与 PlanStore（进程内存）解耦

### 决策 4：WAL mode + 同步 INSERT

**WAL mode**（Write-Ahead Logging）：

```python
def _init_db(self):
    conn = sqlite3.connect(self._db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # 平衡安全与性能
    # CREATE TABLE / CREATE INDEX ...
```

**为什么 WAL？**
- 读写不互斥（普通模式写会阻塞读）
- 崩溃恢复比 DELETE 模式好
- SQLite 推荐的 production 配置

**同步 INSERT**（V0.9.5 取舍）：

ChatGPT V0.9.4 代码审核 Q3 建议："Event handlers should be lightweight and non-blocking。SQLite 以后就知道：不能直接 INSERT，而是后台队列。"

**V0.9.5 决策：同步 INSERT，但在 ADR 明确边界条件**：

| 因素 | V0.9.5 现状 | 阈值 |
|------|------------|------|
| 每 plan events 数 | 8-12 | <100 OK |
| 单次 INSERT 耗时 | <1ms（WAL + synchronous=NORMAL） | <10ms OK |
| 每 plan 总 INSERT 耗时 | <12ms | <100ms OK |
| 并发 | 单进程 CLI | 无并发 |
| 阻塞主流程 | <12ms 不可感知 | <100ms OK |

**结论**：V0.9.5 单进程 CLI 场景，同步 INSERT 符合 "lightweight and non-blocking" 约定（<1ms per INSERT 是 lightweight 的）。

**V1.0+ 升级触发条件**：
- 并发写入（多进程 / Daemon 模式）
- 每 plan events 数 >100
- 单次 INSERT >10ms
- 此时改为后台队列 + 批量 INSERT

### 决策 5：事务边界

**每 event 一个 INSERT**（V0.9.5 简单实现）：

```python
def handle(self, event: ExecutionEvent) -> None:
    conn = sqlite3.connect(self._db_path, timeout=5.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO execution_events (...) VALUES (...)",
            (event.event_id, event.type, event.plan_id, ...)
        )
        conn.commit()
    finally:
        conn.close()
```

**为什么不用连接池 / 长连接？**
- V0.9.5 单进程 CLI，每 plan 8-12 events，连接开销可接受
- 长连接需要管理生命周期（进程退出时关闭）
- V1.0+ 后台队列时再引入长连接 + 批量 commit

**为什么 INSERT OR REPLACE？**
- event_id 是 UUID，理论上不重复
- OR REPLACE 作为防御性编程（万一重复 event_id 不崩溃）
- 语义上：相同 event_id 的 event 是同一个事件（immutable 约定）

**优化选项（V0.9.5 可选）**：用长连接 + context manager：

```python
def __init__(self, db_path):
    self._conn = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    self._init_db()

def handle(self, event):
    self._conn.execute("INSERT OR REPLACE ...", ...)
    self._conn.commit()

def close(self):
    self._conn.close()
```

**ADR 倾向**：长连接版本（性能更好，且 close() 明确管理生命周期）。

### 决策 6：ai-hub history 命令

**新增 CLI**：

```
ai-hub history                       列出最近 N 个 plan execution（默认 20）
ai-hub history --plan <plan_id>      查某个 plan 的完整 event timeline
ai-hub history --limit N             限制条数（默认 20）
ai-hub history --json                JSON 输出
```

**history 默认输出**（列出最近 plan）：

```
AI Hub History — v0.9.5 (SQLite: ~/.ai-hub/execution.db)

Recent executions (5):
  2026-07-17 12:01:00  plan-abc123  2 steps  SUCCESS  500ms
  2026-07-17 11:30:00  plan-def456  3 steps  FAILED   1.2s
  2026-07-16 18:00:00  plan-ghi789  1 step   SUCCESS  200ms
  ...
```

**history --plan <plan_id> 输出**（某个 plan 的 timeline）：

```
AI Hub History — plan-abc123

Task: task-fake-plan-001
Status: SUCCESS
Started: 2026-07-17 12:01:00
Finished: 2026-07-17 12:01:00 (500ms)

Timeline (8 events):
  12:01:00.000  0.0s  plan_started
  12:01:00.001  0.0s  planner_started (RuleBasedPlanner)
  ...
  12:01:00.500  0.5s  plan_finished (SUCCESS, 500ms)
```

**与 trace 命令的区别**：
- `trace`：查内存 TraceCollector（当前进程）
- `history`：查 SQLite（跨进程历史）
- 两者输出格式相似（都是 Timeline），但数据源不同
- ChatGPT 建议只有 CLI 负责组合，两者 Store 互不引用

**history --json 输出**：

```json
{
  "version": "0.9.5",
  "source": "sqlite",
  "db_path": "~/.ai-hub/execution.db",
  "executions": [
    {
      "plan_id": "plan-abc123",
      "task_id": "task-...",
      "status": "success",
      "step_count": 2,
      "started_at": "...",
      "finished_at": "...",
      "total_latency_ms": 500
    }
  ]
}
```

### 决策 7：与 TraceCollector 完全解耦

**ChatGPT V0.9.4 代码审核 Q4 明确建议**：

> 不要做 inspect → Trace Available 以及 trace → Inspect Available 双向引用。
> 只有 CLI 负责组合。

**V0.9.5 实施**：
- SQLiteExecutionStore 不 import TraceCollector
- TraceCollector 不 import SQLiteExecutionStore
- 两者都只订阅 EventBus，互不知道对方存在
- CLI（cli/plan.py）负责同时注入两者到 EventBus

```python
# cli/plan.py（修改）
from planner.event_bus import EventBus
from planner.trace_collector import InMemoryTraceCollector
from planner.sqlite_execution_store import SQLiteExecutionStore

_EVENT_BUS = EventBus()
_TRACE_COLLECTOR = InMemoryTraceCollector()
_TRACE_COLLECTOR.attach(_EVENT_BUS)

_SQLITE_STORE = SQLiteExecutionStore()  # 默认 ~/.ai-hub/execution.db
_SQLITE_STORE.attach(_EVENT_BUS)
```

### 决策 8：数据保留策略

**V0.9.5 不做自动 TTL**（简单）：

- SQLite 文件增长缓慢（每 plan ~12 rows × ~200 bytes = ~2.4KB）
- 1 万次执行 ≈ 24MB，可接受
- V1.0+ 再加自动 TTL / max rows 清理

**手动清理**（V0.9.5 可选命令）：

```
ai-hub history --cleanup --before <date>    删除某日期前的记录
ai-hub history --cleanup --keep <N>         只保留最近 N 条
```

**V0.9.5 范围决策**：`--cleanup` 推迟到 V0.9.6+。V0.9.5 只做查询，不做清理。保持版本克制。

### 决策 9：Core Freeze 维持

- core/ + router/ + providers/ 0 修改
- V0.9.5 全部新增 / 修改在 `planner/` + `cli/`
- SQLiteExecutionStore 是 planner 内部组件
- Provider 不接触 EventBus（ChatGPT Q7 强建议，V0.9.6 再做 token/cost）

### 决策 10：schema_version 维持 "1"

**Postel's Law 延续**（ADR-0017 决策 10）：
- V0.9.5 不改变 plan --json 的 schema
- history --json 是新命令，新 schema，不影响现有
- metadata.schema_version 维持 "1"

## 架构

```
┌─────────────────────┐
│ PlanExecutor        │
│   .execute(task)    │
│                     │
│   emit("plan_...") ─┼──→ EventBus ──→ InMemoryTraceCollector (V0.9.4)
│   emit("step_...") ─┤        │          │
│   emit("provider...")        │          ↓
└─────────────────────┘         │      ai-hub trace
        │                       │      (进程级 Timeline)
        ↓                       │
    PlanStore (V0.9.3)          │
        │                       │
        ↓                       ↓
    ai-hub inspect         SQLiteExecutionStore (V0.9.5 新增)
    (业务视图)                  │
                                ↓
                            ~/.ai-hub/execution.db
                                │
                                ↓
                            ai-hub history
                            (跨进程历史)
```

**关键解耦**：
- `inspect` 查 PlanStore（业务）
- `trace` 查 TraceCollector（当前进程过程）
- `history` 查 SQLiteExecutionStore（跨进程历史）
- 三者共享 `plan_id` 关联，但 Store 之间互不引用
- 只有 CLI 负责组合

## 范围

### 只做

1. `planner/sqlite_execution_store.py`（新增）— SQLiteExecutionStore（EventBus Consumer）
2. `cli/history.py`（新增）— `ai-hub history` 命令
3. `cli/main.py`（修改）— 注册 history 命令
4. `cli/plan.py`（修改）— 注入 SQLiteExecutionStore 到 EventBus
5. `planner/__init__.py`（修改）— 导出 SQLiteExecutionStore
6. 完整测试

### 不做（V0.9.6+ 推迟）

- ❌ token / cost 自动采集（V0.9.6 — Provider 返回 server_metrics → Runtime 转）
- ❌ 自动 TTL / 数据清理（V0.9.6+）
- ❌ 后台队列 / 异步写入（V1.0+ — 并发场景再引入）
- ❌ 跨进程同步（V0.11+ — 真实 Daemon 需求时）
- ❌ 修改 core/ + router/ + providers/
- ❌ ExecutionRecord 完整类（概念预留，V1.0+）
- ❌ history --cleanup（推迟）

## 测试策略

测试覆盖：
- `test_sqlite_execution_store.py`（新增）— 持久化 / 查询 / 环形 / 边界
  - 基本 INSERT + 查询
  - get_events(plan_id)
  - list_plans(limit)
  - has(plan_id)
  - 重复 event_id（INSERT OR REPLACE）
  - WAL mode 验证
  - DB 文件创建
  - detach 后停止接收
  - 长连接 close()
- `test_cli_history.py`（新增）— history 命令
  - 默认列出最近 N 个
  - --plan <plan_id> 查 timeline
  - --json 输出
  - --limit N
  - 空数据库
  - 错误处理（不存在的 plan_id）
- `test_planner.py`（更新）— SQLiteExecutionStore 作为 Consumer 集成测试
- `test_cli_plan.py` / `test_cli_plan_json.py`（更新）— version 0.9.4 → 0.9.5
- `test_cli_inspect.py`（更新）— version 升级

**测试隔离**：每个测试用 tmp_path 创建临时 DB 文件，不污染 ~/.ai-hub/execution.db。

目标：测试基线 268 → 310+ passed。

## 兼容性

- `PlanStore` API 不变
- `TraceCollector` API 不变（V0.9.4 代码不动）
- `PlanExecutor.__init__` 签名不变（event_bus 注入不变）
- `metadata.schema_version` 维持 "1"
- 新增 `ai-hub history` 命令（不影响现有命令）
- 新增 `~/.ai-hub/execution.db`（首次运行自动创建）

## 风险

| 风险 | 缓解 |
|------|------|
| DB 文件损坏 | WAL mode + synchronous=NORMAL（崩溃可恢复）|
| DB 文件增长 | V0.9.5 不限制；V0.9.6+ 加 --cleanup |
| 同步 INSERT 阻塞 | V0.9.5 <1ms per INSERT（可接受）；V1.0+ 后台队列 |
| DB 文件权限 | `~/.ai-hub/` 目录用户可写（默认） |
| 多进程同时写 | V0.9.5 单进程；V0.11+ 再解决（busy_timeout=5.0 已设） |
| SQLite 不可用 | Python 标准库 sqlite3，无外部依赖 |

## 确认问题（发 ChatGPT 审核）

1. **单表 vs 多表**：execution_events 单表 + data JSON 是否足够？还是需要 plans 表 + events 表规范化？
2. **同步 INSERT 取舍**：V0.9.5 单进程 CLI 场景同步 INSERT（<1ms）是否符合 "lightweight" 约定？还是一开始就该后台队列？
3. **长连接 vs 每 event 新连接**：V0.9.5 倾向长连接（性能好，close() 管理生命周期）。是否合理？
4. **DB 路径**：`~/.ai-hub/execution.db` 跨项目共享 vs 项目本地 `.ai-hub/execution.db`？哪个更好？
5. **history vs trace 命令**：history 查 SQLite（跨进程），trace 查内存（当前进程）。命令命名和职责分离是否清晰？用户会不会困惑？
6. **INSERT OR REPLACE 语义**：event_id 是 UUID 理论不重复，OR REPLACE 作为防御。还是应该 INSERT OR IGNORE（拒绝覆盖，因为 Event immutable）？
7. **list_plans 查询**：从 events 表派生 plan 列表（GROUP BY plan_id）vs 维护单独的 plans 索引表？
8. **V0.9.5 范围克制**：不做 cleanup / TTL / 后台队列 / token cost，只做持久化 + history 查询。是否太保守或正好？

## 后续路线

- **V0.9.6**：token / cost 自动采集（Provider 返回 server_metrics → Runtime 转 ExecutionMetrics，Provider 不接触 EventBus）+ history --cleanup
- **V0.10**：Workflow Runtime（Dependency → Conditional → Retry → Checkpoint → Resume）
- **V1.0**：后台队列 + 批量 INSERT（并发场景）+ Subscription Handle（token 模式）

---

## 审核状态

> 待 ChatGPT 外部审核（Proposed）

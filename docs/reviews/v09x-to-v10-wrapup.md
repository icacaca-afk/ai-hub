# V0.9.x → V1.0 整体收官总结

> 时间：2026-07-17
> 范围：V0.9.0（Planner Skeleton）→ V1.0.0（ARCHITECTURE.md 启动基线）
> 状态：Runtime Observability 阶段 + 文档体系入口全部就绪
> 下一阶段：V1.0 Workflow Runtime

---

## 1. 一句话总结

V0.9.x 把 AI Hub 从"Provider Router"演进成"AI Runtime"，并把运行时约定正式文档化。V1.0 在此基础上扩展 Workflow 能力（Condition / Retry / Checkpoint / Resume）。

---

## 2. V0.9.x 完整演化线（最终）

| 版本 | 主题 | ADR 评分 | 代码评分 | 关键产物 |
|------|------|---------|---------|----------|
| V0.9.0~V0.9.2 | Planner Skeleton → LLM Planner | 9.5/10 | — | Planner 抽象 + Plan/Step 数据模型 |
| V0.9.3 | Inspect / PlanStore | 9.98/10 | — | `ai-hub inspect` + PlanStore 环形缓冲 |
| V0.9.4 | ExecutionEvent / Trace | 10.0/10 | 10.0/10 | Event 模型 + EventBus + TraceCollector |
| V0.9.5 | SQLiteExecutionStore | 10.0/10 | 10.0/10 | Event 持久化 + `ai-hub history` |
| V0.9.6 | Provider Metrics | 9.95/10 | 10.0/10 (Final) | Token/Cost 自动采集 + Pricing 接口化 |
| **V0.9.7** | **Execution Analytics** | **9.95/10** | **10.0/10 (Final)** | **query_events + Statistics + ai-hub stats** |
| — | **Runtime Contract** | — | **10.0/10 (Final)** | **运行时约定层** |
| — | **ARCHITECTURE.md** | — | **10.0/10 (Final)** | **文档体系入口** |

**累计 ChatGPT 评分**：
- 全部 9.95+/10
- 4 个 10.0/10 FINAL
- 0 个 NEEDS REVISION

**累计 ChatGPT 调整**：
- 13 项调整全部采纳
- 0 项未采纳

---

## 3. V0.9.x 核心架构（Event Sourcing 四层）

```
V0.9.4  ExecutionEvent（事实）
    │
    │  Source of Truth（原则 A）
    │  Immutable（原则 B）
    │
    ▼
V0.9.5  SQLiteExecutionStore（持久化）
    │
    │  独立 Consumer（不继承 TraceCollector）
    │  Storage Failure ≠ Execution Failure
    │
    ▼
V0.9.6  Provider Metrics（观测）
    │
    │  ExecutionMetrics vs server_metrics 分层（原则 F）
    │  MetricsRouter 临时层（V1.0 退出）
    │
    ▼
V0.9.7  Execution Analytics（分析）
    │
    │  query_events() 统一查询接口
    │  StatisticsCollector Read-Only Projection（原则 C）
    │  Postel's Law（原则 E）
    │
    ▼
V1.0.0  Runtime Contract + ARCHITECTURE.md（约定 + 入口）
    │
    │  6 条核心原则
    │  文档体系：README → ARCHITECTURE → Runtime Contract → ...
    │
    ▼
V1.0+  Workflow Runtime on ExecutionEvent
    │
    │  ADR-0021 ExecutionPipeline
    │  ADR-0022 Retry Policy
    │  ADR-0023 Checkpoint / Resume
    │  ADR-0024 Condition / Branching
    │  ADR-0025 OmniRouteProvider（V1.x）
    │
    ▼
V1.x    Production AI Runtime
```

---

## 4. Runtime Contract 6 条核心原则（已文档化）

| 原则 | 名称 | 来源 |
|------|------|------|
| A | ExecutionEvent 是 Source of Truth | ADR-0017 |
| B | ExecutionEvent 不可变 | ADR-0017 |
| C | Analytics Never Mutates Events | ADR-0020（ChatGPT 唯一补充） |
| D | Storage is Disposable | ADR-0018 |
| E | Postel's Law | ADR-0017 |
| F | ExecutionMetrics vs server_metrics 分层 | ADR-0019 |

**V1.0+ 任何 Runtime 行为变更需更新 Runtime Contract**（不得违反）。

---

## 5. 文档体系入口（已建立）

```
README（V1.0 启动时补写）
    │
    ▼
ARCHITECTURE.md（V1.0 总入口）
    │
    ├── Runtime Contract（运行时约定）
    │
    ├── PROVIDER_SPEC.md（Provider 实现）
    │
    ├── GLOSSARY.md（V1.0 启动时新增）
    │
    ├── DEVELOPMENT.md（V1.0 启动时新增）
    │
    ├── TESTING.md（V1.0 启动时新增）
    │
    ├── docs/adr/（设计决策）
    │   ├── ADR-0008 Core Freeze
    │   ├── ADR-0017 Execution Event
    │   ├── ADR-0018 SQLiteExecutionStore
    │   ├── ADR-0019 Provider Metrics
    │   └── ADR-0020 Execution Analytics
    │
    └── docs/reviews/（ChatGPT 审核记录）
```

---

## 6. V0.9.x 数据能力总览

| 能力 | 命令 | 数据源 | 实现 |
|------|------|--------|------|
| 单次调用 | `ai-hub ask` | — | Router + Provider + Bridge |
| 多步 Plan | `ai-hub plan` | — | Planner + PlanExecutor + EventBus |
| 业务视图 | `ai-hub inspect` | PlanStore | 环形缓冲（10 条） |
| 当前进程 | `ai-hub trace` | InMemoryTraceCollector | 内存环形缓冲 |
| 跨进程历史 | `ai-hub exec-history` | SQLiteExecutionStore | `query_events()` |
| **统计分析** | **`ai-hub stats`** | **SQLiteExecutionStore** | **`query_events()` + StatisticsCollector** |
| Token/Cost | `ai-hub exec-history` 显示 | MetricsRouter | server_metrics 提取 |
| 健康检查 | Router 健康度 | HealthRouter | 实时 |

**所有查询路径收敛到 `query_events()`**（canonical query interface，ADR-0020）。

---

## 7. ChatGPT 对 V0.9.x 的整体评价（最终引用）

> "V0.9.x 到这里已经形成了一条很完整的演化线：
>
> ```
> V0.9.0  Planner Skeleton
>   ↓
> V0.9.3  Plan Model
>   ↓
> V0.9.4  Execution Event
>   ↓
> V0.9.5  Execution Store
>   ↓
> V0.9.6  Runtime Metrics
>   ↓
> V0.9.7  Execution Analytics
> ```
>
> 这个顺序是非常自然的。没有出现"一边开发 Workflow，一边补底层基础设施"，而是先把 Runtime 的观测层和数据层打牢，再进入 Workflow Runtime。
>
> 我认为这是一个更稳健的演化路径。" — V0.9.7 ADR Review

> "我建议将 V1.0 的第一个 ADR 聚焦于 ExecutionPipeline，继续保持你在 V0.9.x 建立的节奏：
> ADR → 审核 → 实现 → 测试 → 冻结。
> 不需要预先设计整个 Workflow Runtime，再逐步扩展 Retry、Checkpoint、Condition 等能力即可。" — Runtime Contract Review

---

## 8. V1.0 启动条件（已满足）

| 条件 | 状态 |
|------|------|
| 运行时模型稳定 | ✅ V0.9.4~V0.9.7 |
| 观测能力闭环 | ✅ Trace + SQLite + Metrics + Statistics |
| 架构约束文档化 | ✅ Runtime Contract |
| 文档体系入口 | ✅ ARCHITECTURE.md |
| V0.9.x 全 ChatGPT 审核 | ✅ 4 个 10.0/10 FINAL |

**V1.0 Workflow Runtime 启动前置全部就绪。**

---

## 9. V1.0 路线（已规划）

| 阶段 | ADR | 主题 | 状态 |
|------|-----|------|------|
| V1.0.0 | — | Runtime Contract + ARCHITECTURE.md | **Accepted ✅** |
| V1.0.1 | **ADR-0021** | **ExecutionPipeline（Decorator 替代 Router 子类）** | **下一轮启动** |
| V1.0.2 | ADR-0022 | Retry Policy | Planned |
| V1.0.3 | ADR-0023 | Checkpoint / Resume | Planned |
| V1.0.4 | ADR-0024 | Condition / Branching | Planned |
| V1.x | ADR-0025 | OmniRouteProvider 融合 | Planned |

**节奏**：

```
ADR (Proposed) → ChatGPT 审核 → 编码 → 测试 → ChatGPT 代码审核 → 冻结 → 下一 ADR
```

不一口气写整个 Workflow Runtime 3000 行 ADR（ChatGPT Runtime Contract Q8 明确建议）。

---

## 10. 关键不变量（V1.0+ 不得违反）

1. **Core Freeze**：core/ + router/router.py + providers/ 永远只读
2. **Runtime Contract**：6 条原则 + 6 个 Contract 章节
3. **Read-Only Projection**：StatisticsCollector 纯函数
4. **Postel's Law**：schema_version 维持 "1"，新字段用 .get() 容错
5. **query_events() canonical**：所有 CLI 收敛到 query_events
6. **ADR → 审核 → 冻结**：每个能力单独 ADR，不一口气写

---

## 11. 收官

V0.9.x Runtime Observability 阶段 + 文档体系入口全部完成。

进入 V1.0：第一个 ADR 是 **ADR-0021 ExecutionPipeline**。

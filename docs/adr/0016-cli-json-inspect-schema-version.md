# ADR-0016: V0.9.3 CLI 完整化（--json + inspect + schema_version）

- **状态**: Proposed
- **日期**: 2026-07-17
- **里程碑**: V0.9.3
- **关联**: ADR-0014（CLI 入口 + metadata 分层）、ADR-0015（LLM Planner）
- **API Stability**: Experimental

## 背景

V0.9.1 把 `ai-hub plan` 接入 CLI，V0.9.2 引入 LLMPlanner。但当前 CLI 仍是「单点 + 人类可读」状态，与 V0.8 `ai-hub explain-route` 的成熟度差距明显：

1. **`--json` 标志占位但未实现**（V0.9.1 承诺「V0.9.3 with explain-plan」）
2. **缺「事后查看 Plan 详情」能力**——`explain-route` 解释的是单次路由，V0.9.2 用户没有「这条 plan 跑了哪几步 / 每步选了哪个 provider / 每步什么状态」的查看入口
3. **metadata 缺 `schema_version`**——V0.9.1 ADR-0014 已留 Reserved，V0.9.2 ChatGPT 审核 9.95/10 再次建议「现在就引入」

ChatGPT 审核明确建议 V0.9.3 CLI 完整化（→ V0.9.4 Execution Trace → V0.10 DAG），本 ADR 采纳。

## 暴露的新需求

### 1. `--json` 真正实现

**问题描述**: V0.9.1 `--json` 只打印提示，WebUI / VSCode Plugin / Dashboard 想消费 Result 元数据必须自己解析人类可读输出，不可靠。

**结论**: `--json` 标志现在真正实现，输出结构化 JSON 到 stdout。V0.9.1 占位删除。

### 2. 新增 `ai-hub inspect` 命令

**问题描述**: 跑完 `ai-hub plan "..."` 后，用户需要：
- 每步选了哪个 Provider（来自 Step.execution_result.provider）
- 每步是什么状态（pending / running / success / failed / skipped）
- 每步的失败原因（来自 Step.execution_result.error）

V0.9.2 只能从 `Result.output` 字符串里看，Dashboard / VSCode Plugin 拿不到结构化数据。

**结论**: 新增 `ai-hub inspect <plan_id>` 命令，根据 `plan_id` 查询 Plan 详情并输出。V0.9.3 阶段 Plan 存放在进程内 `PlanStore`（环形缓冲 N=10），V0.9.4+ 持久化（SQLite / Memory Bus）由后续 ADR 单独定义。

### 3. metadata 引入 `schema_version`

**问题描述**: V0.9.1 顶层冻结 `plan_id` / `task_id`，其他归入 `plan.*` / `runtime.*`。但消费者无法判断 metadata 的 schema 版本：
- Dashboard 解析到 `metadata["plan"]["status"]` 时，无法判断这是 V0.9.1 还是 V0.9.0 的 schema
- 未来 metadata 结构演化时，需要兼容旧数据

**结论**: V0.9.3 在 `metadata` 顶层增加 `schema_version` 字段，值为 `"1"`。允许其作为例外进入顶层（不破坏 ADR-0014 顶层冻结原则——冻结是「不再随意新增业务字段」，schema_version 是元数据管理字段，类似 `Content-Type`）。

`schema_version` 维护规则：
- 当前值：`"1"`（V0.9.3）
- 升级时机：metadata 结构不向后兼容变化时（如新增必填子键、改字段名）
- 兼容策略：消费者先读 `schema_version` → 按版本分发解析逻辑

## 接口变更

| 变更 | 类型 | 向后兼容 | 影响范围 |
|------|------|---------|---------|
| 新增 `planner/plan_store.py`（`PlanStore`） | 新增 | Yes | planner/ |
| 新增 `cli/inspect.py`（`cmd_inspect`） | 新增 | Yes | cli/ |
| 修改 `cli/main.py`（注册 `inspect` + usage + `--json` 文档） | 修改 | Yes | cli/main.py |
| 修改 `cli/plan.py`（`--json` 真正实现） | 修改 | Yes（占位 → 实现） | cli/plan.py |
| 修改 `planner/executor.py`（metadata 加 `schema_version` + PlanStore.save） | 修改 | No（schema 变化） | planner/ |
| 修改 `planner/plan.py`（`to_dict_with_executor_state` 辅助方法） | 修改 | Yes | planner/ |
| 修改 `tests/test_planner.py`（schema_version 断言） | 修改 | Yes | tests/ |
| 新增 `tests/test_plan_store.py` | 新增 | Yes | tests/ |
| 新增 `tests/test_cli_plan_json.py` | 新增 | Yes | tests/ |
| 新增 `tests/test_cli_inspect.py` | 新增 | Yes | tests/ |
| `core/*` | 不修改 | — | — |
| `router/*` | 不修改 | — | — |
| `providers/*` | 不修改 | — | — |
| `planner/plan.py` dataclass 字段 | 不修改 | — | — |

**破坏性变更说明**：`metadata.schema_version` 是新增字段。V0.9.2 的消费者读不到该字段时降级为「未知版本」即可，不破坏现有逻辑。

## 决策

### 1. `--json` 输出 schema

```json
{
  "version": "0.9.3",
  "task": {
    "text": "<原始任务文本>",
    "task_id": "<uuid>"
  },
  "plan": {
    "plan_id": "<uuid>",
    "task_id": "<uuid>",
    "status": "success",
    "created_at": "<ISO timestamp>",
    "steps": [
      {
        "step_id": "step-0",
        "content": "<子任务文本>",
        "capabilities": ["general.chat"],
        "depends_on": [],
        "status": "success",
        "execution_result": {
          "provider": "<provider name>",
          "status": "success",
          "output": "<文本输出>",
          "error": null,
          "artifacts": [],
          "metadata": {}
        }
      }
    ],
    "metadata": {
      "plan": {"status": "success", "steps": 2, "success": 2, "failed": 0},
      "runtime": {"planner": "RuleBasedPlanner", "router": "ScoreRouter"},
      "schema_version": "1"
    }
  }
}
```

**字段命名约定**：
- 顶层 `version`：ai-hub 版本号（与 metadata schema 无关）
- 顶层 `task`：原 Task 描述
- 顶层 `plan`：Plan 完整数据（`Plan.to_dict()` + `execution_result` 已在 `to_dict` 内联）
- `metadata` 用 ADR-0014 既有结构 + 新增 `schema_version`

### 2. `ai-hub inspect` 命令

```bash
ai-hub inspect <plan_id>           # 人类可读
ai-hub inspect <plan_id> --json    # JSON 输出
ai-hub inspect --list              # 列出最近 N 个 plan
ai-hub inspect --list --json       # JSON 列表
```

V0.9.3 范围：**只存当前进程最近 N=10 个 Plan**（环形缓冲）。V0.9.4+ 持久化（SQLite / Memory Bus）由后续 ADR 单独定义。

### 3. `schema_version` 字段

```python
"metadata": {
    "plan_id": "...",
    "task_id": "...",
    "plan": {...},
    "runtime": {...},
    "schema_version": "1",      # V0.9.3 引入
}
```

**维护策略**（ADR 记录）：
- `"1"` = V0.9.3 当前 schema（plan/runtime 分层 + schema_version 字段本身）
- 升级时机：metadata 结构不向后兼容变化时
- 升级前必须先在 ADR 中说明 v1→v2 变化和迁移路径

### 4. CLI 人类可读输出不变

V0.9.1 的 `Status: SUCCESS (2/2)` 等人类可读输出保持不变。`--json` 是平行的另一条输出路径。

### 5. `inspect` 输出格式

人类可读：
```
AI Hub Inspect — v0.9.3

Plan: abc123def456
Task: t1
Status: SUCCESS (2/2)
Created: 2026-07-17T12:00:00+00:00
Planner: RuleBasedPlanner
Router: ScoreRouter
Schema Version: 1

Steps:
  [step-0] success
    Content: 总结 PDF
    Capabilities: [text.summarize]
    Provider: demo
    Duration: N/A
  [step-1] success
    Content: 翻译成英文
    Capabilities: [text.translate]
    Provider: gemini
    Duration: N/A
```

V0.9.3 不引入 Step 级别 `duration_ms`（保留给 V0.9.4+ Execution Trace 引入），输出中 `Duration: N/A` 字段预留。

### 6. PlanStore 接口（V0.9.3 进程内实现）

```python
# planner/plan_store.py
class PlanStore:
    """进程内 Plan 存储（环形缓冲，最多 N=10 个）。"""

    def __init__(self, max_size: int = 10):
        self._store: OrderedDict[str, Plan] = OrderedDict()
        self._max = max_size

    def save(self, plan: Plan) -> None:
        if plan.plan_id in self._store:
            self._store.move_to_end(plan.plan_id)
        else:
            if len(self._store) >= self._max:
                self._store.popitem(last=False)
            self._store[plan.plan_id] = plan

    def get(self, plan_id: str) -> Plan | None:
        return self._store.get(plan_id)

    def list_recent(self, limit: int = 10) -> list[Plan]:
        return list(self._store.values())[-limit:][::-1]
```

V0.9.3 默认 `max_size=10`，CLI 不暴露调整（V0.9.4+ 再考虑 Config）。

### 7. PlanStore 与 PlanExecutor 集成

V0.9.3 不强制 PlanStore 注入 PlanExecutor（避免破坏 PlanExecutor 构造函数签名）。改用「PlanExecutor 暴露 plan_save 钩子，由 CLI 层注入」：

```python
# planner/executor.py
class PlanExecutor:
    def __init__(self, router, planner, plan_store: PlanStore | None = None):
        ...
        self.plan_store = plan_store  # V0.9.3 新增可选参数，向后兼容

    def execute(self, task: Task) -> Result:
        plan = self.planner.decompose(task)
        # ... 执行 ...
        # V0.9.3: 执行后持久化到 plan_store（如果有）
        self.last_plan = plan
        if self.plan_store is not None:
            self.plan_store.save(plan)
        return self._aggregate(plan, task)
```

**向后兼容**：V0.9.2 的 PlanExecutor 调用 `PlanExecutor(router, planner)` 不传 plan_store 仍正常工作（默认 None）。

## V0.9.3 范围

**做**：
- `ai-hub plan --json` 真正实现（结构化 JSON 输出）
- `ai-hub inspect <plan_id>` 命令（人类可读 + `--json`）
- `ai-hub inspect --list` 命令（列出最近 N 个 plan）
- `planner/plan_store.py`（进程内环形缓冲 PlanStore）
- `metadata.schema_version = "1"`
- `PlanExecutor.plan_store` 可选参数（向后兼容）
- 测试：unit + subprocess

**不做**（推迟）：
- ❌ Plan 持久化（SQLite / Memory Bus）—— V0.9.4+ Execution History
- ❌ Step 级别 `duration_ms` / `latency_ms` / `token_in` / `token_out` —— V0.9.4+ Execution Trace
- ❌ Step 失败时的重试 / Resume —— V0.9.4+ Execution Trace
- ❌ inspect 跨进程（依赖持久化）—— V0.9.4+
- ❌ inspect 过滤器（按时间 / 状态）—— V0.9.4+
- ❌ `--max-steps` / `--planner auto` —— V0.9.4+ Config

## 经验教训（预测）

- **`--json` 延后到独立版本**：V0.9.1 占位但不实现是正确的——JSON schema 需要配合 metadata 分层一起设计，提前实现会和后续调整冲突。
- **PlanStore 进程内先行**：V0.9.3 不上持久化是合理克制。10 个 Plan 的环形缓冲覆盖大多数调试场景，V0.9.4+ 持久化是单独立项。
- **`schema_version` 提前**：V0.9.3 引入成本极低（无外部消费者），等到 Dashboard / VSCode 接入后再补兼容性成本高。
- **inspect 与 explain-route 职责正交**：inspect 查 Plan 状态，explain-route 解释单次路由。两者无重叠。
- **PlanExecutor 构造参数向后兼容**：新增 `plan_store` 用默认 None，老调用方零修改。这是 V0.9.0「组合 + 可选依赖」原则的延续。
- **ChatGPT 建议采纳**：9.95/10 审核建议的「V0.9.3 CLI 完整化」准确命中产品化最大缺口。

## Consequences

- 新增 `planner/plan_store.py`：约 60 行
- 新增 `cli/inspect.py`：约 100 行
- 修改 `planner/executor.py`：metadata 加 `schema_version`（约 3 行）+ plan_store.save 调用（2 行）+ 构造函数加可选参数（约 3 行）
- 修改 `cli/plan.py`：`--json` 真正实现（约 30 行）
- 修改 `cli/main.py`：注册 `inspect` 命令 + usage（约 5 行）
- 修改 `planner/plan.py`：可选 `to_dict_with_executor_state` 辅助（约 15 行，仅当 to_dict 不够时）
- 新增 `tests/test_plan_store.py`：约 60 行（8 tests）
- 新增 `tests/test_cli_plan_json.py`：约 100 行（10 tests）
- 新增 `tests/test_cli_inspect.py`：约 100 行（10 tests）
- 修改 `tests/test_planner.py`：metadata schema_version 断言（约 5 行）
- 全量测试预期：251 → ~280+ passed，0 failed
- Core Freeze KPI 保持绿
- `metadata.schema_version` 是新增字段，V0.9.2 消费者向后兼容

## Frozen Impact

- `core/` ✅ 零修改
- `router/router.py` ✅ 零修改
- `router/health_router.py` ✅ 零修改
- `router/score_router.py` ✅ 零修改
- `providers/` ✅ 零修改
- `planner/plan.py` dataclass 字段 ✅ 零修改
- `planner/base.py` ✅ 零修改
- `planner/rule_based_planner.py` ✅ 零修改
- `planner/llm_planner.py` ✅ 零修改
- `planner/plan_validator.py` ✅ 零修改
- `planner/prompts.py` ✅ 零修改
- `planner/executor.py` ⚠️ 修改（metadata 加 `schema_version` + PlanStore.save + 构造可选参数）
- `cli/main.py` ⚠️ 修改（注册 `inspect` 命令 + usage）
- `cli/plan.py` ⚠️ 修改（`--json` 真正实现）
- `planner/plan_store.py` ✅ 新增（本 ADR 核心）
- `cli/inspect.py` ✅ 新增（本 ADR 核心）

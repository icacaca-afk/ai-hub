# ADR-0014: Planner CLI Integration & Execution Metadata

- **状态**: Proposed
- **日期**: 2026-07-17
- **里程碑**: V0.9.1
- **关联**: ADR-0008（Core Freeze）、ADR-0011（Score Router）、ADR-0013（Planner 骨架）
- **API Stability**: Experimental

## 背景

V0.9.0 交付了 Planner Python API（`PlanExecutor` + `RuleBasedPlanner`，33 tests passed）。骨架稳定但用户无法通过命令行使用——目前只有 `ai-hub ask`（单步）和 `ai-hub explain-route`（路由解释），缺一条「复合任务分解 + 多步执行 + 聚合」的入口。

同时，V0.9.0 的聚合 `Result.metadata` 采用扁平结构：

```python
metadata = {
    "plan_id": "...",
    "task_id": "...",
    "planner": "rule_based",
    "plan_status": "success",
    "steps": 3,
    "success": 3,
    "failed": 0,
}
```

审核反馈指出：metadata 已经接近稳定接口，但扁平结构在 V0.10+（latency/token/cost/retry/resume）加入后会无限膨胀。本 ADR 一并解决两个问题——CLI 接入 + metadata 分层。

## 暴露的新需求

### 1. CLI 命令职责分离

**问题描述**: `ai-hub ask` 当前是「单 Task → Router → Provider」链路。如果让 ask 自动走 Planner，会破坏单步执行的明确性，且让 ask 命令的行为变得不可预测（取决于内容是否可切分）。

**结论**: 新增独立命令 `ai-hub plan "..."`，走「Task → Planner → PlanExecutor → Router → Aggregate」链路。`ask` 保持单步语义不变。两条链路独立，用户按需选择。

### 2. metadata 分层（防膨胀）

**问题描述**: 扁平 metadata 在 V0.10+ 会演化成：

```python
# 反例：一年后的膨胀
metadata = {
    "plan_id": ..., "task_id": ..., "planner": ...,
    "plan_status": ..., "steps": ..., "success": ..., "failed": ...,
    "latency_ms": ..., "token_in": ..., "token_out": ..., "cost": ...,
    "retry_count": ..., "resumed_from": ..., "warnings": ...
}
```

字段混杂 plan 信息与 runtime 信息，消费者（CLI / Dashboard / MCP）难以按需取用。

**结论**: 自 V0.9.1 起，metadata 分两层 + 少数稳定顶层字段：

```python
metadata = {
    # 顶层稳定标识（不随版本变化）
    "plan_id": "...",
    "task_id": "...",

    # plan 子键：计划本身的统计（explain-plan / Dashboard 直接消费）
    "plan": {
        "status": "success",     # success / partial / failed
        "steps": 3,
        "success": 3,
        "failed": 0,
    },

    # runtime 子键：执行态信息（V0.10+ 扩展 latency/token/cost/retry）
    "runtime": {
        "planner": "rule_based",
        "router": "score",       # V0.9.1 新增
    },
}
```

**约束（强约束，不允许例外）**：
- **顶层冻结**：除 `plan_id`、`task_id` 外，**不允许新增任何顶层 metadata 字段**。所有新字段必须归入 `plan.*` 或 `runtime.*` 子键。
- `plan.*` 字段 ≤ 6 个（当前 4 个：`status` / `steps` / `success` / `failed`，预留 `skipped` / `duration_ms`）
- `runtime.*` 字段 ≤ 8 个（当前 2 个：`planner` / `router`，预留 `latency_ms` / `token_in` / `token_out` / `cost` / `retry_count` / `resumed_from`）

**版本化（预留）**：metadata schema 将于 V0.9.3 引入 `schema_version` 字段（放入 `runtime`），方便 Dashboard / VSCode / WebUI 升级时做兼容判断。V0.9.1 不实现。

### 3. CLI 不直接访问 Planner 内部对象

**问题描述**: 如果 CLI 直接遍历 `executor.last_plan.steps[i]`，则未来 WebUI / VSCode 插件 / Dashboard 都会复制一遍遍历逻辑，且 Plan 内部结构变化时所有消费者都要改。

**结论**: **Plan 对象不是公共 API。** `Plan` / `Step` / `depends_on` 等全部属于 `planner/` 内部实现。未来 DAG / Graph / Retry Queue / Execution Tree 等内部结构替换时，CLI 不受影响。

CLI 只消费 `Result`（含 `output` / `artifacts` / `metadata`），其中：
- 展示用文本 → `result.output` / `result.artifacts`
- **Planner / Router 信息 → 统一来自 `result.metadata.runtime`**（不读 `executor.planner` 或 `executor.last_plan`）

这样未来替换为 `RemotePlanner` / `MCPPlanner` / `CloudPlanner` 时，CLI 完全不用改。

`executor.last_plan` 保留为 `Optional[Plan]`，仅供调试和未来 `explain-plan`（ADR-0015）使用。

### 4. CLI 输出：先人类可读，JSON 后续

**问题描述**: V0.8 explain-route 同时支持人类可读 + JSON，但 plan 命令的输出结构更复杂（多 Step header + 聚合统计），JSON schema 需要单独设计。

**结论**: V0.9.1 只做人类可读输出。`--json` 标志占位但不实现（输出提示「JSON output will be available in V0.9.3 with explain-plan」）。JSON schema 与 explain-plan 一并在 ADR-0015 设计。

## 接口变更

| 变更 | 类型 | 向后兼容 | 影响范围 |
|------|------|---------|---------|
| 新增 `cli/plan.py`（`cmd_plan`） | 新增 | Yes | cli/ |
| 修改 `cli/main.py`（注册 `plan` 命令 + usage） | 修改 | Yes | cli/main.py |
| 修改 `planner/executor.py`（metadata 分层） | 修改 | **No**（metadata schema 变更） | planner/ |
| 修改 `tests/test_planner.py`（metadata 断言） | 修改 | Yes | tests/ |
| 新增 `tests/test_cli_plan.py` | 新增 | Yes | tests/ |
| 修改 `pyproject.toml`（packages 加 `planner`） | 修改 | Yes | pyproject.toml |
| `core/*` | 不修改 | — | — |
| `router/*` | 不修改 | — | — |
| `providers/*` | 不修改 | — | — |

**破坏性变更说明**：`metadata` schema 从扁平改为分层（`plan_status` → `plan.status`，`steps` → `plan.steps` 等）。V0.9.0 是上一版且无外部消费者，破坏可接受。`test_planner.py` 同步更新断言。

## 架构验证结果

| 核心模块 | 是否修改 | 原因 |
|---------|---------|------|
| `core/task.py` | ❌ | CLI 构造 Task 不改 Task 本身 |
| `core/result.py` | ❌ | metadata 是 `dict[str, Any]`，分层不破坏 Result 接口 |
| `core/provider.py` | ❌ | CLI 不直接访问 Provider |
| `core/registry.py` | ❌ | 通过 ScoreRouter 间接使用 |
| `router/router.py` | ❌ | PlanExecutor 组合调用，不改 Router |
| `router/score_router.py` | ❌ | 同上 |
| `providers/*` | ❌ | CLI 不感知 Provider 实现 |
| `planner/plan.py` | ❌ | Plan/Step 结构不变 |
| `planner/base.py` | ❌ | Planner ABC 不变 |
| `planner/rule_based_planner.py` | ❌ | 分解逻辑不变 |
| `planner/executor.py` | ✅ | metadata 结构从扁平改为分层（本 ADR 核心变更） |
| `cli/main.py` | ✅ | 新增 `plan` 命令注册（非 core，允许修改） |

## 决策

### 1. CLI 命令

```bash
ai-hub plan "<复合任务描述>"
```

链路：

```
CLI cmd_plan
  ↓ Task.from_text(text)
  ↓ ScoreRouter(registry, quota, hr)
  ↓ PlanExecutor(router=score_router, planner=RuleBasedPlanner())
  ↓ executor.execute(task) → Result
  ↓ 打印 Result.output / artifacts / metadata
```

`ask` 与 `plan` 完全独立，无自动切换。

### 2. CLI 输出格式（人类可读）

```
AI Hub Plan — v0.9.1

Task:
  总结这份 PDF 然后翻译成英文

Planner:
  RuleBasedPlanner

Steps:
  ✓ step-0  总结这份 PDF
  ✓ step-1  翻译成英文

Status:
  SUCCESS (2/2)

Output:
[Step 0: 总结这份 PDF]
<step 0 output>

[Step 1: 翻译成英文]
<step 1 output>

Artifacts:
  - summary.pdf
  - translated.txt
```

- `Planner` 行显示类名（如 `RuleBasedPlanner` / `LLMPlanner` / `WorkflowPlanner`），来自 `metadata.runtime.planner`
- Step 状态图标：✓ success / ✗ failed / ⊘ skipped（V0.9.1 不会出现 skipped，占位）
- `Status` 行：状态全大写（`SUCCESS` / `PARTIAL` / `FAILED`）+ `(success/total)`，视觉层级与 docker / git / kubectl 风格一致
- **`--json` 标志**：检测到时打印提示信息 `JSON output will be available in V0.9.3 with explain-plan` 并 **exit code = 0**（未实现 ≠ 错误）

### 3. metadata 分层规范

```python
# planner/executor.py._aggregate() 返回的 Result.metadata
{
    "plan_id": "abc123",                  # 顶层稳定标识（冻结，不再新增顶层字段）
    "task_id": "def456",                  # 顶层稳定标识（冻结，不再新增顶层字段）

    "plan": {
        "status": "success",              # success / partial / failed（CLI 显示时全大写）
        "steps": 2,                       # Step 总数
        "success": 2,                     # 成功数
        "failed": 0,                      # 失败数
    },

    "runtime": {
        "planner": "RuleBasedPlanner",    # planner 类名（非 snake_case），来自 type(planner).__name__
        "router": "ScoreRouter",          # router 类名，来自 type(router).__name__
    },
}
```

**字段配额（强约束）**：
- 顶层：`plan_id` / `task_id`（≤ 2 个，不再增加）
- `plan.*`：`status` / `steps` / `success` / `failed`（≤ 6 个，预留 `skipped` / `duration_ms`）
- `runtime.*`：`planner` / `router`（≤ 8 个，预留 `latency_ms` / `token_in` / `token_out` / `cost` / `retry_count` / `resumed_from`）

### 4. CLI 不访问 Planner 内部

```python
# cli/plan.py — 正确做法
result = executor.execute(task)
# 只读 result.output / result.artifacts / result.metadata
# Planner 名称来自 result.metadata["runtime"]["planner"]
# 不读 executor.planner / executor.last_plan.steps[i].execution_result

# 反例（禁止）：
# for step in executor.last_plan.steps:
#     print(step.execution_result.output)
# print(type(executor.planner).__name__)  # 也不允许
```

`executor.last_plan` 保留为 `Optional[Plan]`，仅供调试和未来 `explain-plan`（ADR-0015）使用。

### 5. pyproject.toml 更新

`packages` 列表新增 `"planner"`，确保 `pip install -e .` 后 `import planner` 可用。同时验证 `planner/__init__.py` 已存在（V0.9.0 已创建），避免「tests pass 但 pip install 后 import 失败」的坑。

### 6. V0.9.1 范围

**做**：
- `ai-hub plan "..."` 命令（人类可读输出，状态全大写，Planner 显示类名）
- metadata 分层（plan / runtime 子键，顶层冻结仅 plan_id/task_id）
- `pyproject.toml` 加 planner 包 + 验证 `planner/__init__.py` 存在
- CLI 测试（subprocess 调用 `ai-hub plan`），包含：
  - 正常多步任务
  - 空输入（`ai-hub plan ""`）
  - `--json` 标志（验证 exit code = 0 + 提示信息输出）
- 更新 test_planner.py 的 metadata 断言（plan.success / runtime.planner 等）

**不做**（推迟）：
- ❌ `--json` 输出（V0.9.3 与 explain-plan 一并设计，ADR-0015）
- ❌ explain-plan（ADR-0015）
- ❌ LLM Planner（V0.9.2）
- ❌ Step 级别 latency / token 统计（V0.10+）
- ❌ Step 失败时的交互式 retry（V0.10+）

## 经验教训（预测）

- **CLI 只消费 Result**：这是 Planner 对外契约的稳定锚点。Plan 内部结构（Step 字段、依赖图）未来会随 V0.10 DAG 变化，但 Result 接口稳定，CLI 不受影响。
- **metadata 分层趁早**：V0.9.0 → V0.9.1 改分层成本极低（无外部消费者）。等到 V0.10+ 多个消费者出现后再改，需同步迁移 CLI / Dashboard / MCP。
- **`ask` 与 `plan` 分离**：避免「智能切换」带来的不可预测性。用户明确选择单步还是多步，比让系统猜测意图更可靠。
- **JSON 延后**：人类可读输出先验证产品形态，JSON schema 与 explain-plan 一并设计避免反复调整。

## Consequences

- 新增 `cli/plan.py`，约 80 行
- 修改 `cli/main.py`：新增 `plan` 命令注册 + usage 行（约 5 行）
- 修改 `planner/executor.py`：metadata 分层（约 15 行）
- 修改 `tests/test_planner.py`：metadata 断言更新（约 10 行）
- 新增 `tests/test_cli_plan.py`：CLI subprocess 测试（约 80 行）
- 修改 `pyproject.toml`：packages 加 `planner`（1 行）
- 全量测试预期：194 → ~200+ passed，0 failed
- Core Freeze KPI 保持绿
- metadata schema 破坏性变更（V0.9.0 → V0.9.1），无外部消费者，可接受

## Frozen Impact

- `core/` ✅ 零修改
- `router/router.py` ✅ 零修改
- `router/health_router.py` ✅ 零修改
- `router/score_router.py` ✅ 零修改
- `providers/` ✅ 零修改
- `planner/plan.py` ✅ 零修改
- `planner/base.py` ✅ 零修改
- `planner/rule_based_planner.py` ✅ 零修改
- `planner/executor.py` ⚠️ 修改（metadata 分层，本 ADR 核心变更）
- `cli/main.py` ⚠️ 修改（新增命令注册，非 core）

# ADR-0027: Runtime Metadata Schema — 运行时元数据统一 (V1.0.7)

- **里程碑**: V1.0.7
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: **Draft v2** (采纳 ChatGPT 9.2/10 Q4 additive migration，重新提交审核)
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0022 RetryStage](0022-retry-stage.md), [ADR-0023 CheckpointStage](0023-checkpoint-stage.md), [ADR-0024 ConditionStage](0024-condition-stage.md), [ADR-0025 PipelineHooks](0025-pipeline-hooks.md), [ADR-0026 StageDescriptor](0026-stage-descriptor.md)
- **后续**: V1.0.8 Stage Registry (V2 评估)
- **前序 ChatGPT 路线图**: V1.0.6 代码审核 9.95/10 FINAL — "V1.0.7 推进: Runtime Metadata Schema 统一"
- **历史**: v1 (9.2/10 NEEDS REVISION) 已被本 v2 取代。`docs/reviews/0027-adr-chatgpt-review-raw.txt` 保留 v1 审核记录。

> **StageDescriptor 答 "What is a Stage?" (静态元数据)**
> **RuntimeMetadata 答 "What happened during execution?" (动态元数据)**
> **本 ADR 让两者解耦 + 规范化 — 通过 additive migration，不破坏 V1.0.x 公共 API。**

---

## 1. 背景与目标

### 1.1 背景

V1.0.x 已经引入多个 Stage，每个 Stage 在 `ctx.metadata` 中写入自己的运行时数据：

| Stage | metadata key | 数据结构 | 引入版本 |
|-------|--------------|----------|---------|
| `MetricsStage` | `"server_metrics"` | `dict[str, Any]` | V1.0.1 |
| `RetryStage` | (无, V1.1 进入 Result.metadata) | — | V1.0.3 |
| `ConditionStage` | `"condition_eval"` | `dict` (ConditionEval.to_dict) | V1.0.4 |
| `CheckpointStage` | (读 `condition_eval.stopped_by`) | — | V1.0.3+ |
| `PlanExecutor` | `"plan"` | `{"success": N, "failed": M}` | V1.0.1 |

**重要事实**：当前 `ExecutionContext` 是非 frozen dataclass，`ctx.metadata` 字段**不在** dataclass 字段中，而是通过 `setattr(ctx, "metadata", {})` 在 `ConditionStage.__call__` 中动态注入（首次写入时）。这意味着：

- 第三方 Stage 当前也用 `ctx.metadata["key"] = value` 风格
- Hook 也用 `ctx.metadata["key"]` 读取
- `Result.metadata: dict` 是另一套独立 dict（不受影响）

### 1.2 当前痛点

**1. 命名空间冲突风险 (Naming Collision Risk)**

```python
ctx.metadata["server_metrics"] = {...}  # MetricsStage
ctx.metadata["server_metrics"] = "broken"  # 第三方 Stage (无 namespace)
```

- ❌ **无 namespace 隔离**：任何 Stage 都能写 `ctx.metadata["any_key"]`
- ❌ **无 schema 约束**：每个 Stage 自己定义结构
- ❌ **无访问控制**：读端只能假设结构

**2. 跨 Stage 隐式耦合 (Implicit Cross-Stage Coupling)**

```python
# CheckpointStage 必须知道 ConditionStage 写入的 key
class CheckpointStage:
    def _extract_stopped_by(self, ctx):
        return ctx.metadata.get("condition_eval", {}).get("stopped_by") or "stop_flag"
```

- ❌ **字符串约定**：用 `"condition_eval"` 字符串读
- ❌ **脆弱**：ConditionStage 改 key 即破坏 CheckpointStage

**3. 文档化不足 (Lack of Documentation)**

- Runtime Contract 仅约定 `ctx.metadata: dict[str, Any]`，没有"哪些 key 是 V1.x reserved"
- 第三方 Stage 不清楚哪些 key 已被 built-in Stage 使用

### 1.3 目标（v2 修订）

本 ADR 引入 **RuntimeMetadata** — 强类型的运行时元数据容器。**关键 v2 变更**：采用 **additive migration**（采纳 ChatGPT 9.2/10 Q4 关键反馈）：

- **保留** `ctx.metadata: dict[str, Any]`（V1.0.6 行为完全不变）
- **新增** `ctx.runtime: RuntimeMetadata`（强类型 dataclass）
- built-in Stage **同时**写 `ctx.runtime.*` 和 `ctx.metadata["*"]`（双写，向后兼容）
- 第三方 Stage 旧 `ctx.metadata["key"]` 写法**完全不受影响**
- 新代码 `ctx.runtime.condition_eval` 逐步迁移
- V2 评估：deprecate `ctx.metadata` 写入（仅 `ctx.runtime` 强类型）

### 1.4 非目标

- ❌ **不**破坏 V1.0.x 公共 API（采纳 ChatGPT 9.2/10 关键反馈）
- ❌ **不**做 schema validation (Pydantic / JSON Schema)
- ❌ **不**做 metadata 持久化 (ExecutionStore 已有, 不重复)
- ❌ **不**做 metadata 加密 / 签名
- ❌ **不**改 Stage 行为 (仅改 metadata 写入方式)
- ❌ **不**改 Hook 签名 (V1.0.6 Hook 已 Approved)
- ❌ **不**deprecate `ctx.metadata` (V1.0.7 仅 additive 引入)
- ❌ **不**在 V1.0.7 加 `retry` 字段 (V1.1 再加，采纳 ChatGPT 9.2/10)
- ❌ **不**在 V1.0.7 加 `experimental` 字段 (V2 再加，采纳 ChatGPT 9.2/10)

---

## 2. 设计（v2 修订）

### 2.1 RuntimeMetadata 数据模型

```python
# planner/runtime_metadata.py (NEW)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Optional

from planner.stages.condition_stage import ConditionEval  # V1.0.4


@dataclass
class RuntimeMetadata:
    """运行时元数据容器 (V1.0.7 — additive migration).

    v2 关键设计 (采纳 ChatGPT 9.2/10 Q4):
      - 强类型属性 (渐进引入)
      - Namespace 隔离 (避免 key 冲突)
      - V1.0.7 MUST: server_metrics / condition_eval / stopped_by / plan / custom
      - V1.1: 加 retry
      - V2: 加 experimental
      - 允许 user plugin 写 custom.* 字段 (受控 namespace)

    关键不变量 (Runtime Contract §10):
      - 保留 ctx.metadata: dict[str, Any] (V1.0.6 行为完全不变)
      - 新增 ctx.runtime: RuntimeMetadata (强类型)
      - built-in Stage 双写: ctx.runtime.* + ctx.metadata["*"] (向后兼容)
      - user plugin 旧风格 ctx.metadata["key"] = value 仍可工作
      - 新代码应优先写 ctx.runtime.* (V2 deprecated ctx.metadata 写入)
    """

    # V1.0.7 MUST: server metrics
    server_metrics: Dict[str, Any] = field(default_factory=dict)

    # V1.0.7 MUST: condition eval (ConditionStage 写入, CheckpointStage 读取)
    condition_eval: Optional[ConditionEval] = None

    # V1.0.7 MUST: stopped_by (提升为顶级字段, 采纳 ChatGPT 9.2/10)
    # 不再嵌套在 condition_eval 下, 而是与 condition_eval 平级
    # 原因: 未来 Retry / ManualAbort / Timeout / Cancellation / Hook 都可 stop
    stopped_by: Optional[str] = None

    # V1.0.7 MUST: plan aggregation (PlanExecutor 写入)
    plan: Dict[str, int] = field(default_factory=dict)
    # e.g. {"success": 3, "failed": 1, "skipped": 0, "total": 4}

    # V1.0.7 MUST: user plugin namespace (受控前缀)
    custom: Dict[str, Any] = field(default_factory=dict)
    # 第三方 Stage 写入: runtime.custom["my_plugin"] = {...}

    # V1.0.7 NOT: retry (V1.1 再加, 采纳 ChatGPT 9.2/10)
    # 原因: RetryStage V1.0.3 根本没有 metadata, V1.1 完整设计再加

    # V1.0.7 NOT: experimental (V2 再加, 采纳 ChatGPT 9.2/10)
    # 原因: Reserved Field 维护成本几乎为零, 但 Runtime Contract 要解释
    #       V2 真需要再加


# V1.0.7 reserved namespace (Runtime Contract §10 文档化)
RUNTIME_RESERVED_KEYS: FrozenSet[str] = frozenset({
    "server_metrics",
    "condition_eval",
    "stopped_by",
    "plan",
    "custom",
})
```

### 2.2 ExecutionContext 集成（v2 additive migration）

```python
# planner/pipeline.py (V1.0.7 增量)
from planner.runtime_metadata import RuntimeMetadata

@dataclass
class ExecutionContext:
    """Pipeline 透传的不可变上下文 (V1.0.7 additive).

    v2 关键变更:
      - 新增 runtime: RuntimeMetadata 字段 (V1.0.7 引入)
      - 保留 metadata: dict[str, Any] 动态注入 (V1.0.6 行为不变)
      - 双写策略: built-in Stage 写 runtime + metadata (向后兼容)
    """
    task: Task
    provider: Optional[Provider] = None
    bridge: Any = None
    bridge_result: Optional[BridgeResult] = None
    result: Optional[Result] = None
    stop: bool = False

    # V1.0.7 新增: 强类型运行时元数据 (与 metadata 并存)
    runtime: RuntimeMetadata = field(default_factory=RuntimeMetadata)
    # 注: 保留旧的动态 metadata 注入, 第三方 Stage 旧风格不受影响

    # with_xxx helpers 也保留 metadata 透传
    def with_provider(self, provider, bridge=None):
        new_ctx = ExecutionContext(...)
        new_ctx.metadata = self.metadata  # 透传
        new_ctx.runtime = self.runtime    # 透传
        return new_ctx
    # ... 其他 with_xxx 类似
```

**v2 关键约束 (采纳 ChatGPT 9.2/10):**
- ✅ `ctx.metadata: dict` **完全保留**（旧 API 不变）
- ✅ **新增** `ctx.runtime: RuntimeMetadata`（新 API）
- ✅ built-in Stage **双写**：写 `ctx.runtime.*`（新）+ `ctx.metadata["*"]`（旧）
- ✅ 第三方 Stage 旧 `ctx.metadata["key"]` 写法**完全不受影响**
- ✅ 第三方 Stage 新写法可同时写 `ctx.runtime.custom["my_key"]`
- ❌ **不**做迁移警告（V1.0.7 不破坏任何东西，无需 warning）
- ❌ **不**标记 `ctx.metadata` 为 deprecated（V2 才 deprecated）

### 2.3 Stage 集成（v2 双写策略）

```python
class ConditionStage:
    def __call__(self, ctx):
        if ctx.task is None or ctx.bridge_result is None:
            return ctx
        try:
            result = bool(self.condition(ctx))
        except Exception as e:
            logger.warning(...)
            result = False
        action = self.on_true if result else self.on_false
        stopped_by = None
        if action == "skip":
            stopped_by = f"condition:{self._name}:skip"
        elif action == "abort":
            stopped_by = f"condition:{self._name}:abort"

        # V1.0.7: 构造强类型 ConditionEval
        condition_eval = ConditionEval(
            stage="condition",
            condition_name=self._name,
            result=result,
            action=action,
            timestamp=time.time(),
            stopped_by=stopped_by,
        )

        # V1.0.7 v2: 双写 (采纳 ChatGPT 9.2/10 additive migration)
        # 新 API (强类型, 推荐)
        ctx.runtime.condition_eval = condition_eval
        if stopped_by is not None:
            ctx.runtime.stopped_by = stopped_by
        # 旧 API (向后兼容, 第三方 / Hook 仍能读)
        if not hasattr(ctx, "metadata") or ctx.metadata is None:
            ctx.metadata = {}
        ctx.metadata["condition_eval"] = condition_eval.to_dict()
        if stopped_by is not None:
            ctx.metadata["stopped_by"] = stopped_by

        if action in ("skip", "abort"):
            ctx.stop = True
        return ctx


class MetricsStage:
    def __call__(self, ctx):
        if ctx.bridge_result is None:
            return ctx
        # V1.0.7 v2: 强类型 + 双写
        new_metrics = self.extractor.extract(ctx.bridge_result)
        # 新 API
        ctx.runtime.server_metrics = {**(ctx.runtime.server_metrics or {}), **new_metrics}
        # 旧 API (保留 backward compat)
        if not hasattr(ctx, "metadata") or ctx.metadata is None:
            ctx.metadata = {}
        existing = ctx.metadata.get("server_metrics", {})
        ctx.metadata["server_metrics"] = {**existing, **new_metrics}
        return ctx


class CheckpointStage:
    def _extract_stopped_by(self, ctx):
        # V1.0.7 v2: 强类型优先, dict 兜底 (additive)
        # 关键: 优先读 ctx.runtime.stopped_by, 兜底 ctx.metadata["condition_eval"].stopped_by
        if hasattr(ctx, "runtime") and ctx.runtime is not None:
            if ctx.runtime.stopped_by is not None:
                return ctx.runtime.stopped_by
            if ctx.runtime.condition_eval is not None:
                return ctx.runtime.condition_eval.stopped_by
        # 兜底: 旧 dict 风格
        if hasattr(ctx, "metadata") and ctx.metadata is not None:
            condition_eval = ctx.metadata.get("condition_eval")
            if isinstance(condition_eval, dict):
                stopped_by = condition_eval.get("stopped_by")
                if stopped_by:
                    return stopped_by
        return "stop_flag"
```

### 2.4 PlanExecutor 集成

```python
class PlanExecutor:
    def _aggregate_results(self, task_results):
        return {
            "success": sum(1 for r in task_results if r.is_success),
            "failed": sum(1 for r in task_results if not r.is_success),
            "total": len(task_results),
        }

    def execute(self, plan):
        ...
        aggregated = ...
        # V1.0.7 v2: 双写 plan
        aggregated.runtime.plan = self._aggregate_results(results)
        aggregated.metadata["plan"] = self._aggregate_results(results)
        return aggregated
```

### 2.5 V1.x reserved namespaces（Runtime Contract §10）

| Namespace | Owner | 类型 | 说明 |
|-----------|-------|------|------|
| `ctx.runtime.server_metrics` | MetricsStage | `Dict[str, Any]` | 服务端 metrics |
| `ctx.runtime.condition_eval` | ConditionStage | `Optional[ConditionEval]` | 条件求值结果 |
| `ctx.runtime.stopped_by` | ConditionStage / Pipeline | `Optional[str]` | 终止来源（顶级字段） |
| `ctx.runtime.plan` | PlanExecutor | `Dict[str, int]` | 计划聚合 |
| `ctx.runtime.custom` | user plugin | `Dict[str, Any]` | 第三方 Stage 受控 namespace |
| `ctx.metadata["*"]` | any (legacy) | `Dict[str, Any]` | **保留**旧 dict API（V2 deprecated） |

**禁止：**
- built-in Stage 写 `custom.*`（污染 user plugin namespace）
- user plugin 写 reserved keys（`server_metrics` / `condition_eval` / `stopped_by` / `plan`）

**允许：**
- user plugin 写 `runtime.custom.my_plugin` 命名空间
- user plugin 写 `metadata["legacy_key"]` 旧风格（V1.0.x 永久兼容）
- user plugin 写 `runtime.custom["legacy_key"]` 新风格

### 2.6 V1.x 兼容性（v2 关键 — Additive Migration）

**关键 v2 设计（采纳 ChatGPT 9.2/10）：** V1.0.7 **不破坏任何现有 API**。所有 V1.0.6 行为完全保留：

```python
# 旧代码 (V1.0.6, 第三方 Stage / Hook) — V1.0.7 完全不受影响
ctx.metadata["my_plugin_key"] = value  # ✅ 仍工作 (旧 dict API 保留)
condition_eval = ctx.metadata.get("condition_eval")  # ✅ 仍工作
stopped_by = ctx.metadata.get("condition_eval", {}).get("stopped_by")  # ✅ 仍工作

# 新代码 (V1.0.7, built-in Stage) — 推荐新写法
ctx.runtime.condition_eval = ConditionEval(...)  # ✅ 强类型
ctx.runtime.stopped_by = "condition:abort"  # ✅ 顶级字段
ctx.runtime.custom["my_plugin"] = value  # ✅ 受控 namespace
```

**V2 弃用路径（评估）：**
- V1.0.7: built-in Stage **同时**写 runtime + metadata
- V1.0.8: 文档化 `ctx.metadata` 写入 → `ctx.runtime` 迁移路径
- V1.0.9-V1.x: 继续双写
- V2: deprecated `ctx.metadata` 写入（仅 `ctx.runtime` 强类型），但**保留**读取

---

## 3. 关键决策（v2 修订）

### 3.1 为什么 additive migration 而非 breaking change？

**采纳 ChatGPT 9.2/10 Q4 关键反馈：**

- ✅ **不破坏插件 API**：第三方 Stage `ctx.metadata["key"]` 完全不受影响
- ✅ **不破坏 Hook**：Hook `ctx.metadata["trace_id"]` 仍工作
- ✅ **未来 Migration 更容易**：V2 可以平滑 deprecate `ctx.metadata`
- ✅ **生态几乎零成本**：旧代码无需任何改动
- ✅ **符合 Django / SQLAlchemy / FastAPI 演进模式**

### 3.2 为什么 dataclass？

- ✅ **简单**：V1.x 不引入 Pydantic 依赖
- ✅ **类型安全**：属性访问有 mypy 提示
- ✅ **运行时一致**：`isinstance(ctx.runtime, RuntimeMetadata)` 直接验证
- ✅ **default_factory 简单**：`field(default_factory=dict)` 比 Pydantic 轻量

**V2 评估：** Pydantic schema validation (V2 路线)

### 3.3 为什么 `stopped_by` 提升为顶级字段？

**采纳 ChatGPT 9.2/10 关键反馈：**

- ✅ 停止原因**不是 Condition 专属**：未来 Retry / ManualAbort / Timeout / Cancellation / Hook 都可 stop
- ✅ 与 `condition_eval` 平级，符合语义
- ✅ CheckpointStage 读 `ctx.runtime.stopped_by` 一次，不用 `.get().get()` 链
- ✅ Architecture Improvement

### 3.4 为什么 `custom` 命名空间？

- ✅ 隔离 user plugin 写入
- ✅ Runtime Contract §10 显式文档化
- ✅ 未来 V2 可加 validation (e.g. size limit)
- ✅ 长期收益最大的设计点

### 3.5 为什么 V1.0.7 不加 `retry` 字段？（采纳 ChatGPT 9.2/10）

- ❌ RetryStage V1.0.3 根本没有真正 metadata
- ❌ V1.0.7 加空 `field` = Runtime Contract 多一个 reserved 字段但无人用
- ✅ V1.1 完整设计 Retry metadata 后再加

### 3.6 为什么 V1.0.7 不加 `experimental` 字段？（采纳 ChatGPT 9.2/10）

- ❌ Reserved Field 维护成本几乎为零
- ❌ 但 Runtime Contract 需解释它是什么 / 为什么存在 / 什么时候用
- ❌ 最后：没人用
- ✅ V2 真需要再加

### 3.7 为什么 V1.0.7 不 deprecate `ctx.metadata`？

- ❌ Deprecate 但保留读取 = 旧 dict 仍工作，无收益
- ❌ 同时 deprecate 读取 = 仍是 breaking change
- ✅ V1.0.7 仅 additive 引入
- ✅ V2 评估 deprecate 写入路径

### 3.8 为什么 Stage 双写而非只写 runtime？

- ✅ 旧代码读 `ctx.metadata["condition_eval"]` 仍工作
- ✅ 旧 Hook 仍工作
- ✅ 旧第三方 Stage 不感知 RuntimeMetadata 类
- ✅ 新代码读 `ctx.runtime.condition_eval` 类型安全
- ✅ V2 评估移除双写中的 metadata 写入

---

## 4. 替代方案（v2 修订）

### 4.1 替代 1：v1 breaking change（已 reject）

- ❌ 破坏插件 API
- ❌ 破坏 Hook
- ❌ 未来 Migration 更困难
- **结论：reject（ChatGPT 9.2/10 Q4）**

### 4.2 替代 2：保留 dict，仅文档化 reserved keys

- ❌ 无法类型安全
- ❌ 仍可写冲突 key
- ❌ 文档化弱约束

### 4.3 替代 3：v2 additive + 双写（采纳）

- ✅ 旧 API 100% 保留
- ✅ 新 API 强类型
- ✅ Stage 双写提供 migration bridge
- **结论：adopt（v2 采纳方案）**

### 4.4 替代 4：用 Pydantic BaseModel

- ❌ 引入外部依赖
- ❌ V1.x 范围内过度工程
- **结论：defer（V2 评估）**

### 4.5 替代 5：拆多个子对象（MetadataBag / MetricsBag / ConditionBag）

- ❌ 增加 API 复杂度
- ❌ Stage 仍需 import 多个类
- ✅ RuntimeMetadata 单一类足够

### 4.6 替代 6：保留 dict + 增加 dict_to_metadata() 工厂

- ❌ dict API 仍暴露，破坏约束
- ❌ runtime 检查开销

---

## 5. 影响范围（v2 修订）

### 5.1 改动的文件

| 文件 | 改动 |
|------|------|
| `planner/runtime_metadata.py` (NEW) | RuntimeMetadata dataclass + RUNTIME_RESERVED_KEYS |
| `planner/pipeline.py` | ExecutionContext 新增 `runtime: RuntimeMetadata` 字段（保留 metadata） |
| `planner/stages/condition_stage.py` | **双写** `ctx.runtime.condition_eval` + `ctx.metadata["condition_eval"]` |
| `planner/stages/metrics_stage.py` | **双写** `ctx.runtime.server_metrics` + `ctx.metadata["server_metrics"]` |
| `planner/stages/checkpoint_stage.py` | 强类型优先读 `ctx.runtime.stopped_by`，dict 兜底 |
| `planner/stages/retry_stage.py` | V1.0.7 不变（V1.1 再加 metadata.retry） |
| `planner/executor.py` | **双写** `ctx.runtime.plan` + `ctx.metadata["plan"]` |
| `tests/test_runtime_metadata.py` (NEW) | RuntimeMetadata 单元测试 (12+ tests) |
| `tests/test_condition_stage.py` | 增量测试双写 + 强类型 |
| `tests/test_checkpoint_stage.py` | 增量测试强类型读优先 + dict 兜底 |
| `tests/test_metrics_stage.py` | 增量测试双写 |
| `docs/runtime-contract.md` | 新增 §10 Runtime Metadata Schema（additive migration 文档） |

### 5.2 兼容性（v2 关键 — 100% 兼容）

- ✅ **零 Breaking Change**：`ctx.metadata: dict` 完全保留
- ✅ 第三方 Stage `ctx.metadata["key"] = value` **完全不受影响**
- ✅ Hook `ctx.metadata["key"]` 读取 **完全不受影响**
- ✅ 公共 API (`Pipeline.run()` / `default_pipeline()`) 签名不变
- ✅ V1.0.6 全部测试无需修改

### 5.3 Core Freeze 影响

- ❌ **不**改 `core/` 下任何文件
- ❌ **不**改 `router/router.py`
- ❌ **不**改 `providers/`
- ✅ 仅 `planner/` 内扩展

---

## 6. 测试策略（v2 修订）

### 6.1 RuntimeMetadata 单元测试 (12+)

- `test_default_runtime_metadata` — 默认值
- `test_server_metrics_default_dict` — server_metrics 默认可写
- `test_condition_eval_optional` — condition_eval 默认 None
- `test_stopped_by_optional` — stopped_by 默认 None
- `test_plan_default_dict` — plan 默认可写
- `test_custom_default_dict` — custom 默认可写
- `test_no_retry_field` — V1.0.7 确认无 retry 字段（采纳 ChatGPT）
- `test_no_experimental_field` — V1.0.7 确认无 experimental 字段（采纳 ChatGPT）
- `test_runtime_reserved_keys_listed` — RUNTIME_RESERVED_KEYS 完整
- `test_user_plugin_can_write_custom` — custom 命名空间可写
- `test_metadata_equality` — dataclass eq
- `test_stopped_by_top_level_not_nested` — stopped_by 顶级（非 condition_eval 子字段）

### 6.2 ExecutionContext 双写测试 (5+)

- `test_execution_context_has_runtime_field` — ExecutionContext 新增 runtime 字段
- `test_execution_context_metadata_preserved` — metadata 仍可动态注入
- `test_with_xxx_propagates_runtime` — with_xxx 透传 runtime
- `test_runtime_and_metadata_independent` — runtime 和 metadata 互不影响
- `test_default_runtime_metadata_for_context` — default 是空 RuntimeMetadata

### 6.3 Stage 双写测试 (6+)

- `test_condition_stage_writes_both_runtime_and_metadata` — 双写 condition_eval
- `test_condition_stage_stopped_by_top_level` — stopped_by 写顶级
- `test_metrics_stage_writes_both_runtime_and_metadata` — 双写 server_metrics
- `test_checkpoint_stage_prefers_runtime_over_metadata` — 强类型优先读
- `test_checkpoint_stage_falls_back_to_dict` — 旧 dict 仍可读
- `test_plan_executor_writes_both_runtime_and_metadata` — 双写 plan

### 6.4 兼容性测试 (3+)

- `test_third_party_plugin_legacy_dict_still_works` — `ctx.metadata["key"]` 仍工作
- `test_hook_legacy_dict_read_still_works` — Hook 读 `ctx.metadata["trace_id"]` 仍工作
- `test_no_warning_emitted_for_legacy_writes` — V1.0.7 不发 warning（V2 再 deprecated）

### 6.5 V1.0.x 回归测试

- ✅ V1.0.6 全部 32+ 测试无需修改
- ✅ 全量 184+ 测试通过

---

## 7. 实施计划（v2 修订）

### 7.1 阶段 1: RuntimeMetadata 基础 (Day 1)

- `planner/runtime_metadata.py` (NEW)
- `tests/test_runtime_metadata.py` (NEW)
- 12+ 单元测试通过

### 7.2 阶段 2: ExecutionContext 集成 (Day 1-2)

- `ExecutionContext.runtime: RuntimeMetadata` (新增, 非 Breaking)
- `with_xxx` 透传 runtime
- 5+ ExecutionContext 测试

### 7.3 阶段 3: Stage 双写改造 (Day 2)

- ConditionStage 双写 condition_eval + stopped_by
- MetricsStage 双写 server_metrics
- CheckpointStage 强类型优先 + dict 兜底
- PlanExecutor 双写 plan
- 6+ Stage 测试

### 7.4 阶段 4: 兼容性验证 (Day 2)

- 第三方 Stage 旧风格兼容测试
- Hook 旧风格兼容测试
- 3+ 兼容性测试

### 7.5 阶段 5: 全量回归 (Day 2-3)

- V1.0.x 全量测试 (200+ tests)
- Runtime Contract §10 同步
- ChatGPT 代码审核
- ADR-0027 Accepted

---

## 8. ChatGPT v2 审核请求

> **本 ADR v2 草案的关键变更（采纳 v1 9.2/10 反馈）：**
>
> 1. **Q4 迁移策略**：v1 breaking change → **v2 additive migration**（保留 ctx.metadata，新增 ctx.runtime）。这是 v1 的阻塞项，v2 是否解决？
>
> 2. **字段集精简**：删除 `retry`（V1.1 再加）、`experimental`（V2 再加）。V1.0.7 字段：`server_metrics` / `condition_eval` / `stopped_by` / `plan` / `custom`。是否合理？
>
> 3. **Stage 双写策略**：built-in Stage 写 `ctx.runtime.*`（新） + `ctx.metadata["*"]`（旧）。是否过度？是否应只写 runtime？
>
> 4. **`stopped_by` 顶级字段**：从 `condition_eval.stopped_by` 提升为 `ctx.runtime.stopped_by`。是否破坏 V1.0.4 Runtime Contract？
>
> 5. **不 deprecate ctx.metadata**：V1.0.7 保留 ctx.metadata 读取 + 写入。V2 才 deprecated。是否符合渐进式迁移？
>
> 6. **V1.0.8 Stage Registry 接口**：RuntimeMetadata 是否给 Registry 留好接口？`descriptor.metadata_field` 是否需要？
>
> 7. **测试覆盖**：12+5+6+3 = 26+ 测试是否足够？是否需要 property-based test？
>
> 8. **V1.0.7 → V1.0.8 演进**：Stage Registry / Metadata Access API / Schema Versioning — 哪些是 V1.0.8 MUST？

**期望评分：9.5+/10**

---

## 9. v1 → v2 修订说明

| 维度 | v1 (9.2/10) | v2 (本次修订) | 依据 |
|------|-------------|---------------|------|
| 迁移策略 | Breaking: `ctx.metadata: dict → RuntimeMetadata` | Additive: 保留 `ctx.metadata`，新增 `ctx.runtime` | ChatGPT 9.2/10 Q4 阻塞项 |
| `retry` 字段 | V1.0.7 预留空 field | V1.1 再加 | ChatGPT 9.2/10 retry 建议 |
| `experimental` 字段 | V1.0.7 预留空 field | V2 再加 | ChatGPT 9.2/10 experimental 建议 |
| `stopped_by` 提升 | 顶级字段（v1 已采纳） | 顶级字段（v2 保留） | ChatGPT 9.2/10 赞同 |
| `custom` 命名空间 | 受控 namespace | 受控 namespace（保留） | ChatGPT 9.2/10 赞同 |
| dataclass | 采纳 | 采纳（保留） | ChatGPT 9.2/10 赞同 |
| Stage 改造 | 单写 runtime | **双写 runtime + metadata** | additive migration 必需 |
| 旧 `ctx.metadata` 兼容 | 写破坏（`ctx.metadata["k"]` 失效） | **100% 兼容** | additive migration 核心 |
| 期望评分 | 9.2/10 (NEEDS REVISION) | 9.5+/10 (期望 APPROVED) | — |

---

## 10. V1.0.6 → V1.0.7 演化图

```
V1.0.6 (当前):
  ctx.metadata = {}  # 动态注入 dict
  ctx.metadata["condition_eval"] = {...}  # 字符串 key, 无约束
  ctx.metadata["server_metrics"] = {...}  # 字符串 key, 无约束
  → 跨 Stage 隐式耦合 (CheckpointStage 读字符串 key)

V1.0.7 v2 (本次采纳):
  ctx.runtime = RuntimeMetadata()  # 强类型 dataclass (新增)
  ctx.runtime.condition_eval = ConditionEval(...)  # 属性访问, 类型安全 (新)
  ctx.runtime.stopped_by = "condition:abort"  # 顶级字段 (新)
  ctx.metadata["condition_eval"] = {...}  # 旧 API 100% 保留 (向后兼容)
  → 双写策略: 新代码读 runtime, 旧代码读 metadata, 互不影响
```

**关键演进：**
- 无类型 → 强类型（新增 runtime）
- 字符串 key → 属性（新增 runtime）
- 跨 Stage 隐式耦合 → 显式契约（runtime 显式 + 旧 dict 兜底）
- 无 namespace → 隔离 `custom` 命名空间（runtime.custom）
- V1.x reserved keys 文档化 (Runtime Contract §10)
- **零 Breaking Change**：旧 `ctx.metadata["*"]` 完全保留

---

## 11. 关联

- **前序**: [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10)
- **后续**: V1.0.8 Stage Registry (V2 评估) / V1.1 RetryStage 完整 `metadata.retry`
- **V2 路线**: Pydantic schema validation / Plugin discovery via `metadata.custom.*` / deprecate `ctx.metadata` 写入
- **Runtime Contract**: §10 (待写)
- **ARCHITECTURE**: §2.3 V1.0 路线 (Runtime Observability)
- **v1 审核记录**: `docs/reviews/0027-adr-chatgpt-review-raw.txt` (9.2/10 NEEDS REVISION)

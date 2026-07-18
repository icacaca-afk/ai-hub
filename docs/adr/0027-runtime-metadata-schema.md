# ADR-0027: Runtime Metadata Schema — 运行时元数据统一 (V1.0.7)

- **里程碑**: V1.0.7
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: **Draft** (待 ChatGPT 审核)
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0022 RetryStage](0022-retry-stage.md), [ADR-0023 CheckpointStage](0023-checkpoint-stage.md), [ADR-0024 ConditionStage](0024-condition-stage.md), [ADR-0025 PipelineHooks](0025-pipeline-hooks.md), [ADR-0026 StageDescriptor](0026-stage-descriptor.md)
- **后续**: V1.0.8 Stage Registry (V2 评估)
- **前序 ChatGPT 路线图**: V1.0.6 代码审核 9.95/10 FINAL — "V1.0.7 推进: Runtime Metadata Schema 统一"

> **StageDescriptor 答 "What is a Stage?" (静态元数据)**
> **RuntimeMetadata 答 "What happened during execution?" (动态元数据)**
> **本 ADR 让两者解耦 + 规范化。**

---

## 1. 背景与目标

### 1.1 背景

V1.0.x 已经引入多个 Stage，每个 Stage 在 `ctx.metadata` 中写入自己的运行时数据：

| Stage | metadata key | 数据结构 | 引入版本 |
|-------|--------------|----------|---------|
| `MetricsStage` | `"server_metrics"` | `dict[str, Any]` | V1.0.1 |
| `RetryStage` | (无, V1.1 进入 Result.metadata) | — | V1.0.3 |
| `ConditionStage` | `"condition_eval"` | `ConditionEval` (dataclass) | V1.0.4 |
| `CheckpointStage` | (读 `condition_eval.stopped_by`) | — | V1.0.3+ |
| `PlanExecutor` | `"plan"` | `{"success": N, "failed": M}` | V1.0.1 |

### 1.2 当前痛点

**1. 命名空间冲突风险 (Naming Collision Risk)**

```python
# 不同 Stage 可能用同样的 key 写不同结构
ctx.metadata["server_metrics"] = {...}  # MetricsStage
ctx.metadata["server_metrics"] = "broken"  # 第三方 Stage (无 namespace)
```

- ❌ **无 namespace 隔离**：任何 Stage 都能写 `ctx.metadata["any_key"]`
- ❌ **无 schema 约束**：每个 Stage 自己定义结构
- ❌ **无访问控制**：读端只能假设结构

**2. 跨 Stage 隐式耦合 (Implicit Cross-Stage Coupling)**

```python
# CheckpointStage 必须知道 ConditionStage 写入的 key
# (V1.0.4 引入: CheckpointSnapshot.from_context 读 condition_eval.stopped_by)
class CheckpointStage:
    def _extract_stopped_by(self, ctx):
        # 隐式契约: 依赖 ConditionStage 写入了 condition_eval.stopped_by
        return ctx.metadata.get("condition_eval", {}).get("stopped_by") or "stop_flag"
```

- ❌ **字符串约定**：用 `"condition_eval"` 字符串读
- ❌ **脆弱**：ConditionStage 改 key 即破坏 CheckpointStage

**3. 文档化不足 (Lack of Documentation)**

- Runtime Contract 仅约定 `ctx.metadata: dict[str, Any]`，没有"哪些 key 是 V1.x reserved"
- 第三方 Stage 不清楚哪些 key 已被 built-in Stage 使用

### 1.3 目标

本 ADR 引入 **RuntimeMetadata** — 强类型的运行时元数据容器，替代 `ctx.metadata: dict`：

- **类型安全**：用 dataclass / TypedDict 替代 dict
- **Namespace 隔离**：所有 built-in 元数据放在 `RuntimeMetadata` 类属性下
- **V1.x reserved keys 文档化**：所有 built-in key 在 Runtime Contract §10 列出
- **V1.x 兼容**：旧 Stage 仍可写 `ctx.metadata["legacy_key"]`，但有 warning
- **解耦跨 Stage 读**：CheckpointStage 读 `ctx.metadata.condition_eval` 属性，而非 dict.get

### 1.4 非目标

- ❌ **不**做 schema validation (Pydantic / JSON Schema)
- ❌ **不**做 metadata 持久化 (ExecutionStore 已有, 不重复)
- ❌ **不**做 metadata 加密 / 签名
- ❌ **不**改 Stage 行为 (仅改 metadata 写入方式)
- ❌ **不**改 Hook 签名 (V1.0.6 Hook 已 Approved)

---

## 2. 设计

### 2.1 RuntimeMetadata 数据模型

```python
from dataclasses import dataclass, field
from typing import Any, Optional, Dict
from planner.stages.condition_stage import ConditionEval  # V1.0.4

@dataclass
class RuntimeMetadata:
    """运行时元数据容器 (V1.0.7).

    关键设计:
      - 强类型属性 (替代 ctx.metadata: dict)
      - Namespace 隔离 (避免 key 冲突)
      - V1.x reserved: condition_eval / server_metrics / stopped_by / plan / retry
      - 允许 user plugin 写 custom_* 字段 (受控 namespace)

    关键不变量 (Runtime Contract §10):
      - built-in 元数据 MUST 用命名属性 (e.g. metadata.condition_eval = ...)
      - user plugin 元数据 MUST 用 custom_* 前缀 (受控 namespace)
      - 不允许直接 ctx.metadata["any_key"] = ... 写入 built-in key
    """
    # V1.0.1: server metrics
    server_metrics: Dict[str, Any] = field(default_factory=dict)

    # V1.0.4: condition eval (ConditionStage 写入, CheckpointStage 读取)
    condition_eval: Optional[ConditionEval] = None

    # V1.0.5: stopped_by (V1.0.7 提取为顶级字段, 兼容 condition_eval.stopped_by)
    stopped_by: Optional[str] = None

    # V1.0.7: plan aggregation (PlanExecutor 写入)
    plan: Dict[str, int] = field(default_factory=dict)
    # e.g. {"success": 3, "failed": 1, "skipped": 0}

    # V1.0.7: retry tracking (V1.1 完整进入, V1.0.7 预留)
    retry: Dict[str, Any] = field(default_factory=dict)
    # e.g. {"total_attempts": 3, "final_status": "success"}

    # V1.0.7: user plugin namespace (受控前缀)
    custom: Dict[str, Any] = field(default_factory=dict)
    # 第三方 Stage 写入: metadata.custom["my_plugin"] = {...}

    # V1.0.7: experimental / future (V1.x 不使用, V2 扩展)
    experimental: Dict[str, Any] = field(default_factory=dict)
```

### 2.2 ExecutionContext 集成

```python
# V1.0.7: ExecutionContext.metadata 改为 RuntimeMetadata 实例
@dataclass
class ExecutionContext:
    task: Task
    result: Optional[Result] = None
    provider: Optional[Provider] = None
    bridge: Optional[Bridge] = None
    bridge_result: Optional[BridgeResult] = None
    stop: bool = False

    # V1.0.7: 从 dict[str, Any] 改为 RuntimeMetadata
    # 关键: 属性名仍是 metadata, 避免破坏 V1.0.x
    metadata: RuntimeMetadata = field(default_factory=RuntimeMetadata)
    # ↑ Backwards-compat: 旧代码 ctx.metadata["key"] 会失败 (dict API → RuntimeMetadata 属性)
    #   这是 Breaking Change, V1.0.7 必须同步更新所有 built-in Stage
```

**Breaking Change (V1.0.7):**
- 旧 `ctx.metadata["server_metrics"]` 写法 → 新 `ctx.metadata.server_metrics`
- 旧 `ctx.metadata["condition_eval"]` → 新 `ctx.metadata.condition_eval`
- 所有 built-in Stage 同步更新

### 2.3 Stage 集成

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

        # V1.0.7: 强类型写入
        ctx.metadata.condition_eval = ConditionEval(
            stage_name=self._name,
            result=result,
            action=action,
            stopped_by=stopped_by,
        )
        # V1.0.7: stopped_by 提升为顶级字段
        if stopped_by is not None:
            ctx.metadata.stopped_by = stopped_by
        if action in ("skip", "abort"):
            ctx.stop = True
        return ctx


class MetricsStage:
    def __call__(self, ctx):
        if ctx.bridge_result is None:
            return ctx
        # V1.0.7: 强类型读取
        existing = ctx.metadata.server_metrics or {}
        server_metrics = {**existing, **self.extractor.extract(ctx.bridge_result)}
        ctx.metadata.server_metrics = server_metrics
        return ctx


class CheckpointStage:
    def _extract_stopped_by(self, ctx):
        # V1.0.7: 强类型读取 (替代 dict.get)
        # 关键: 不再依赖 ctx.metadata.get("condition_eval")
        if ctx.metadata.stopped_by is not None:
            return ctx.metadata.stopped_by
        if ctx.metadata.condition_eval is not None:
            return ctx.metadata.condition_eval.stopped_by
        return "stop_flag"
```

### 2.4 PlanExecutor 集成

```python
# V1.0.7: PlanExecutor 写入 plan aggregation
class PlanExecutor:
    def _aggregate_results(self, task_results):
        success = sum(1 for r in task_results if r.is_success)
        failed = sum(1 for r in task_results if not r.is_success)
        return {
            "success": success,
            "failed": failed,
            "total": len(task_results),
        }

    def execute(self, plan):
        ...
        # V1.0.7: 强类型写入
        aggregated.metadata.plan = self._aggregate_results(results)
        ...
```

### 2.5 V1.x reserved keys (Runtime Contract §10)

| Key | Owner | 类型 | 说明 |
|-----|-------|------|------|
| `server_metrics` | MetricsStage | `Dict[str, Any]` | 服务端 metrics |
| `condition_eval` | ConditionStage | `Optional[ConditionEval]` | 条件求值结果 |
| `stopped_by` | ConditionStage / Pipeline | `Optional[str]` | 终止来源 |
| `plan` | PlanExecutor | `Dict[str, int]` | 计划聚合 (success/failed/total) |
| `retry` | RetryStage (V1.1 完整) | `Dict[str, Any]` | 重试统计 |
| `custom` | user plugin | `Dict[str, Any]` | 第三方 Stage 受控 namespace |
| `experimental` | V2 评估 | `Dict[str, Any]` | 实验性字段 |

**禁止：** built-in Stage 写 `custom.*`；user plugin 写 reserved keys。
**允许：** user plugin 写 `custom.my_plugin` 命名空间。

### 2.6 V1.0.x 兼容 (Migration Path)

**关键：** V1.0.7 是 Breaking Change（`ctx.metadata` 类型从 `dict` 变 `RuntimeMetadata`）。但所有 built-in Stage 同步更新，user plugin 仍可通过 `custom` namespace 写旧 dict 风格：

```python
# user plugin 旧风格 (V1.0.6)
ctx.metadata["my_plugin_key"] = value  # ❌ 不再工作 (dict API 消失)

# user plugin 新风格 (V1.0.7)
ctx.metadata.custom["my_plugin_key"] = value  # ✅ 工作 (受控 namespace)
```

**V1.0.7 Migration Helper (可选):**

```python
# V1.0.7: 检测 user plugin 旧风格并 emit warning
def _legacy_metadata_warning():
    logger.warning(
        "ctx.metadata['key'] = ... is deprecated in V1.0.7. "
        "Use ctx.metadata.custom['key'] = ... instead. "
        "See ADR-0027."
    )
```

---

## 3. 关键决策

### 3.1 为什么用 dataclass 而非 TypedDict / Pydantic？

- ✅ **dataclass 简单**：V1.x 不引入 Pydantic 依赖
- ✅ **类型安全**：属性访问有 mypy 提示
- ✅ **运行时一致**：`isinstance(ctx.metadata, RuntimeMetadata)` 直接验证
- ✅ **default_factory 简单**：`field(default_factory=dict)` 比 Pydantic 轻量

**V2 评估：** Pydantic schema validation (V2 路线图)

### 3.2 为什么 `stopped_by` 提升为顶级字段？

来自 V1.0.4 ChatGPT 9.95/10 关键采纳：

> "Checkpoint 总是写 (即使 abort), 移除 ctx.stop 短路"
> "CheckpointSnapshot 从 ctx.metadata.condition_eval.stopped_by 提取, 兜底 stop_flag"

V1.0.7 显式化：`stopped_by` 是 Pipeline / Checkpoint 共用的关键字段，提到顶级更清晰。

### 3.3 为什么 `custom` 命名空间？

- ✅ 隔离 user plugin 写入
- ✅ Runtime Contract §10 显式文档化
- ✅ 未来 V2 可加 validation (e.g. size limit)

### 3.4 为什么 `experimental` 字段？

- ✅ V1.x 不使用，预留 V2 扩展
- ✅ Stage 可标记 `descriptor.experimental=True` (V1.0.6) 并写入 `experimental.*` 字段
- ✅ V2 Stage 可消费 experimental 元数据

### 3.5 为什么 `retry` 字段在 V1.0.7 预留但未启用？

- V1.0.3 RetryStage 仅写日志，未写入 `ctx.metadata`
- V1.1 完整进入 `metadata.retry` (ChatGPT 9.93/10 路线)
- V1.0.7 预留字段，避免 V1.1 再做 Breaking Change

---

## 4. 替代方案

### 4.1 替代 1：保留 dict，仅文档化 reserved keys

- ❌ 无法类型安全
- ❌ 仍可写冲突 key
- ❌ 文档化弱约束

### 4.2 替代 2：用 Pydantic BaseModel

- ❌ 引入外部依赖
- ❌ V1.x 范围内过度工程

### 4.3 替代 3：拆多个子对象（MetadataBag / MetricsBag / ConditionBag）

- ❌ 增加 API 复杂度
- ❌ Stage 仍需 import 多个类
- ✅ RuntimeMetadata 单一类足够

### 4.4 替代 4：保留 dict + 增加 dict_to_metadata() 工厂

- ❌ dict API 仍暴露，破坏约束
- ❌ runtime 检查开销

---

## 5. 影响范围

### 5.1 改动的文件

| 文件 | 改动 |
|------|------|
| `planner/runtime_metadata.py` (NEW) | RuntimeMetadata dataclass + reserved keys 列表 |
| `planner/pipeline.py` | ExecutionContext.metadata 类型从 dict → RuntimeMetadata |
| `planner/stages/condition_stage.py` | 写 `ctx.metadata.condition_eval` / `stopped_by` (属性) |
| `planner/stages/metrics_stage.py` | 写 `ctx.metadata.server_metrics` (属性) |
| `planner/stages/checkpoint_stage.py` | 读 `ctx.metadata.stopped_by` / `condition_eval` (属性) |
| `planner/stages/retry_stage.py` | 预留 `ctx.metadata.retry` (V1.1 完整) |
| `planner/executor.py` | 写 `aggregated.metadata.plan` (属性) |
| `tests/test_runtime_metadata.py` (NEW) | RuntimeMetadata 单元测试 (10+ tests) |
| `tests/test_condition_stage.py` | 增量测试强类型 metadata |
| `tests/test_checkpoint_stage.py` | 增量测试强类型读 |
| `tests/test_metrics_stage.py` | 增量测试强类型写 |
| `docs/runtime-contract.md` | 新增 §10 Runtime Metadata Schema |

### 5.2 兼容性

- ❌ **Breaking Change：** `ctx.metadata: dict` → `ctx.metadata: RuntimeMetadata`
- ✅ 所有 built-in Stage 同步更新
- ✅ user plugin 用 `custom` namespace 受控迁移
- ✅ 公共 API (`Pipeline.run()` / `default_pipeline()`) 签名不变

### 5.3 Core Freeze 影响

- ❌ **不**改 `core/` 下任何文件
- ❌ **不**改 `router/router.py`
- ❌ **不**改 `providers/`
- ✅ 仅 `planner/` 内扩展

---

## 6. 测试策略

### 6.1 RuntimeMetadata 单元测试 (10+)

- `test_default_runtime_metadata` — 默认值
- `test_server_metrics_default_dict` — server_metrics 默认可写
- `test_condition_eval_optional` — condition_eval 默认 None
- `test_stopped_by_optional` — stopped_by 默认 None
- `test_plan_default_dict` — plan 默认可写
- `test_retry_default_dict` — retry 默认可写
- `test_custom_default_dict` — custom 默认可写
- `test_experimental_default_dict` — experimental 默认可写
- `test_all_reserved_keys_listed` — RESERVED_KEYS 完整
- `test_user_plugin_can_write_custom` — custom 命名空间可写
- `test_metadata_equality` — dataclass eq

### 6.2 Stage 集成测试 (5+)

- `test_condition_stage_writes_typed_metadata` — ConditionStage 写强类型
- `test_metrics_stage_writes_typed_server_metrics` — MetricsStage 写强类型
- `test_checkpoint_stage_reads_typed_metadata` — CheckpointStage 读强类型
- `test_plan_executor_writes_typed_plan` — PlanExecutor 写强类型
- `test_pipeline_backwards_compat_via_custom` — user plugin 仍可通过 custom namespace

### 6.3 迁移测试 (3+)

- `test_legacy_dict_access_fails` — `ctx.metadata["key"]` 抛 AttributeError
- `test_v100_v106_user_plugin_warning` — 旧 user plugin 写 dict 触发 warning
- `test_custom_namespace_isolation` — custom.* 不影响 reserved keys

---

## 7. 实施计划

### 7.1 阶段 1: RuntimeMetadata 基础 (Day 1)

- `planner/runtime_metadata.py` (NEW)
- `tests/test_runtime_metadata.py` (NEW)
- 10+ 单元测试通过

### 7.2 阶段 2: ExecutionContext 集成 (Day 1-2)

- `ExecutionContext.metadata: RuntimeMetadata` (Breaking)
- 所有 built-in Stage 同步更新 (Condition / Metrics / Checkpoint / Retry)
- PlanExecutor 写 plan

### 7.3 阶段 3: 迁移 + 警告 (Day 2)

- 旧 `dict` 访问 emit warning
- user plugin `custom` namespace 文档化
- 增量测试通过

### 7.4 阶段 4: 全量回归 (Day 2)

- V1.0.x 全量测试 (184+)
- Runtime Contract §10 同步
- ChatGPT 代码审核

---

## 8. ChatGPT 审核请求

> **本 ADR 草案的关键问题 (待 ChatGPT 评审):**
>
> 1. **RuntimeMetadata 字段集**：server_metrics / condition_eval / stopped_by / plan / retry / custom / experimental — 是否过宽或过窄？哪些 V1.0.7 必须，哪些 V2？
>
> 2. **dataclass vs TypedDict vs Pydantic**：V1.0.7 用 dataclass 是否正确？V2 应否升级 Pydantic？
>
> 3. **`stopped_by` 提升为顶级字段**：V1.0.4 ChatGPT 采纳但未提升，是否本 ADR 该提升？会不会破坏 V1.0.4 Runtime Contract？
>
> 4. **Breaking Change 处理**：`ctx.metadata: dict → RuntimeMetadata` 是 breaking，是否应 V1.0.7 全面推倒？还是 dual-API (`ctx.metadata` 仍为 dict，新增 `ctx.runtime` 强类型)？
>
> 5. **`custom` 命名空间**：user plugin 受控 namespace 策略是否过严？是否应允许完全自由 (V1.x risk)？
>
> 6. **`experimental` 字段**：V1.x 不使用是否值得预留？还是 V1.0.7 不加 V2 再加？
>
> 7. **`retry` 字段在 V1.0.7 预留但 V1.1 启用**：V1.0.7 加 empty `field` 是否过早？还是 V2 加？
>
> 8. **V1.0.x 兼容性测试**：user plugin 旧 `ctx.metadata["key"]` 写法 — V1.0.7 emit warning 还是 hard fail？
>
> 9. **测试覆盖**：10 + 5 + 3 测试是否足够？是否需要 property-based test (Hypothesis)？
>
> 10. **V1.0.8 Stage Registry 准备**：RuntimeMetadata 是否给 Registry 留好接口？例如 `descriptor.metadata_field = "condition_eval"`？

**期望评分：9.5+/10**

---

## 9. V1.0.6 → V1.0.7 演化图

```
V1.0.6:
  ctx.metadata = {}  # dict[str, Any]
  ctx.metadata["condition_eval"] = ConditionEval(...)  # 字符串 key, 无约束
  ctx.metadata["server_metrics"] = {...}                # 字符串 key, 无约束
  → 跨 Stage 隐式耦合 (CheckpointStage 读字符串 key)

V1.0.7:
  ctx.metadata = RuntimeMetadata()  # 强类型 dataclass
  ctx.metadata.condition_eval = ConditionEval(...)  # 属性访问, 类型安全
  ctx.metadata.server_metrics = {...}                # 属性访问, 类型安全
  → 跨 Stage 显式契约 (CheckpointStage 读 metadata.stopped_by 属性)
```

**关键演进：**
- dict → dataclass (类型安全)
- 字符串 key → 属性 (编译期检查)
- 跨 Stage 隐式耦合 → 显式契约
- 无 namespace → 隔离 `custom` 命名空间
- V1.x reserved keys 文档化 (Runtime Contract §10)

---

## 10. 关联

- **前序**: [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10)
- **后续**: V1.0.8 Stage Registry (V2 评估) / V1.1 RetryStage 完整 `metadata.retry`
- **V2 路线**: Pydantic schema validation / Plugin discovery via metadata.custom.*
- **Runtime Contract**: §10 (待写)
- **ARCHITECTURE**: §2.3 V1.0 路线 (Runtime Observability)

# ADR-0026: StageDescriptor — Stage 元数据描述对象 (V1.0.6)

- **里程碑**: V1.0.6
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: **Draft** (待 ChatGPT 审核)
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0023 CheckpointStage](0023-checkpoint-stage.md), [ADR-0024 ConditionStage](0024-condition-stage.md), [ADR-0025 PipelineHooks](0025-pipeline-hooks.md)
- **前序 ChatGPT 路线图**: V1.0.5 代码审核 9.93/10 FINAL — "V1.0.6 StageDescriptor：用统一描述对象替代基于 stage.name 的字符串约定，为未来扩展（分类、能力标签、可观测性）打基础"

> **StageDescriptor = Stage 的元数据 (Metadata).**
> Stage 关注: 行为 (Behavior).
> StageDescriptor 关注: 描述 (Description) — 名字 / 版本 / 能力 / 副作用特征.
> Pipeline / Hooks / ExecutionStore 通过 Descriptor 认识 Stage，不再依赖 `name` 字符串约定。

---

## 1. 背景与目标

### 1.1 背景

V1.0.1 - V1.0.5 已经建立了完整的 Stage 体系：

| Stage | 引入版本 | 字符串 `name` | 备注 |
|-------|---------|---------------|------|
| `RouteStage` | V1.0.1 | `"route"` | 路由到 Provider |
| `MetricsStage` | V1.0.1 | `"metrics"` | 收 metrics |
| `RetryStage` | V1.0.3 | `"retry"` | 重试 |
| `CheckpointStage` | V1.0.3 | `"checkpoint"` | **特例：V1.0.4 走 duck typing `name + hasattr(store)` 识别** |
| `ConditionStage` | V1.0.4 | `"condition"` | 条件分支 |

### 1.2 当前痛点

**1. 字符串约定 (String-Based Convention)**
Pipeline 内部通过 `stage.name` 字符串来识别 Stage 角色：

```python
# planner/pipeline.py V1.0.4
if stage.name == "checkpoint" and hasattr(stage, "store"):
    ctx = stage(ctx)
```

- ❌ **脆弱**：Stage 重命名即破坏 Pipeline
- ❌ **不类型安全**：字符串拼写错误无编译期保护
- ❌ **不可扩展**：新角色 = 新字符串 = 改 Pipeline

**2. 重复耦合 (Repeated Coupling)**

```python
# 多个位置都用字符串识别
if stage.name == "checkpoint":
    ...

# V1.0.4 ChatGPT 9.95/10 指出: 这是 V1.0.4 唯一轻微耦合
```

**3. Hooks 拿不到 Stage 元数据**

```python
# V1.0.5 Hooks 只能拿到 stage_name 字符串
def before_stage(ctx, stage_name: str):
    # 不知道 Stage 的能力 / 版本 / 是否 idempotent / 是否 experimental
    ...
```

### 1.3 目标

本 ADR 引入 **StageDescriptor**：Stage 的元数据描述对象，替代字符串约定：

- **类型安全**：用 dataclass 而非字符串
- **可扩展**：未来增加 Stage 角色 = 增加 Descriptor 字段，不改 Pipeline
- **解耦 Pipeline**：`Pipeline.run()` 不再 `stage.name == "checkpoint"`，改用 `descriptor.role`
- **赋能 Hooks**：Hooks 收到 `StageDescriptor`，而非裸字符串
- **V1.0.x 兼容**：旧 Stage 用默认 Descriptor 平滑迁移

### 1.4 非目标

- ❌ **不**做 Stage 注册中心 / Registry（V2 评估）
- ❌ **不**改 Stage 的 `__call__(ctx)` 签名（V1.x 冻结）
- ❌ **不**做 Stage 的 schema validation（V2 评估）
- ❌ **不**做 Stage 的自动文档生成（V2 评估）
- ❌ **不**改 Hook 签名（V1.0.5 已 Approved）

---

## 2. 设计

### 2.1 StageDescriptor 数据模型

```python
from dataclasses import dataclass, field
from typing import Optional, Set

@dataclass(frozen=True)  # V1.0.6: 不可变
class StageDescriptor:
    """Stage 元数据描述 (V1.0.6).

    关键不变量:
      - 不可变 (frozen=True)
      - 与 Stage 实例解耦 (1:1 but separate)
      - 默认值兼容 V1.0.x 旧 Stage
    """
    # 必填: 身份
    name: str                # 唯一 ID, e.g. "route" / "metrics" / "checkpoint"
    version: int = 1         # Stage 版本 (V1.0.6: 1)

    # 角色 (V1.0.6 引入)
    role: str = "stage"      # 角色: "stage" | "checkpoint" | "condition" | "retry" | "metric"

    # 能力标签
    capabilities: Set[str] = field(default_factory=set)
    # e.g. {"persists_state"} / {"controls_flow"} / {"retries"}

    # 副作用特征
    idempotent: bool = True         # 多次执行是否安全
    has_side_effects: bool = False  # 是否修改外部状态 (e.g. 写 ExecutionStore / 调 Provider)

    # 运行时特征
    always_run_after_stop: bool = False  # 即使 ctx.stop=True 仍执行 (V1.0.4 Checkpoint 关键)
    experimental: bool = False           # 是否实验性 (V1.0.6 Hook 可见)

    # 元数据
    description: str = ""          # 人类可读描述
    owner: str = "ai-hub"          # 维护者
```

### 2.2 Stage 集成 Descriptor

```python
class Stage:
    """V1.0.6: Stage 基类 (Optional — V1.0.6 提供, 但不强求继承)."""

    descriptor: ClassVar[StageDescriptor] = StageDescriptor(name="stage")

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        raise NotImplementedError


class RouteStage(Stage):
    descriptor = StageDescriptor(
        name="route",
        version=1,
        role="stage",
        capabilities={"selects_provider"},
        idempotent=True,
        has_side_effects=False,
        description="Routes task to a Provider via Router",
    )

    def __call__(self, ctx):
        ...


class MetricsStage(Stage):
    descriptor = StageDescriptor(
        name="metrics",
        version=1,
        role="metric",
        capabilities={"collects_metrics"},
        idempotent=True,
        has_side_effects=False,
        description="Collects per-stage metrics",
    )


class RetryStage(Stage):
    descriptor = StageDescriptor(
        name="retry",
        version=1,
        role="retry",
        capabilities={"retries"},
        idempotent=False,  # 重试 -> 多次副作用
        has_side_effects=True,
        description="Retries failed bridge execution",
    )


class CheckpointStage(Stage):
    descriptor = StageDescriptor(
        name="checkpoint",
        version=1,
        role="checkpoint",
        capabilities={"persists_state"},
        idempotent=True,
        has_side_effects=True,         # 写 ExecutionStore
        always_run_after_stop=True,    # V1.0.4 关键: 即使 abort 仍写
        description="Persists execution snapshot to ExecutionStore",
    )


class ConditionStage:
    """V1.0.6: 加 descriptor (Stage 仍可非继承)."""
    descriptor = StageDescriptor(
        name="condition",
        version=1,
        role="condition",
        capabilities={"controls_flow"},
        idempotent=True,
        has_side_effects=False,
        description="Conditional branch: continue / skip / abort",
    )
```

### 2.3 Pipeline.run() V1.0.6 重构

**之前 (V1.0.5):** 字符串识别 Checkpoint

```python
# V1.0.4 - V1.0.5: duck typing
if stage.name == "checkpoint" and hasattr(stage, "store"):
    ctx = stage(ctx)
```

**之后 (V1.0.6):** 基于 Descriptor

```python
# V1.0.6: 类型安全 + 解耦
if stage.descriptor.always_run_after_stop:
    ctx = stage(ctx)
```

**关键改进：**
- ✅ 不再识别 `"checkpoint"` 字符串
- ✅ 不再 `hasattr(stage, "store")` 探测
- ✅ Pipeline 只关心 `descriptor.always_run_after_stop` 语义
- ✅ CheckpointStage 重命名仍可工作
- ✅ ConditionStage 也可设 `always_run_after_stop=True` (未来)

### 2.4 Hook 演进 (V1.0.6 增强，不改 API)

**V1.0.5 Hook 签名 (Approved)：**
```python
def before_stage(ctx, stage_name: str): ...
def after_stage(ctx, stage_name: str): ...
def on_error(ctx, stage_name: str, exc: Exception): ...
```

**V1.0.6 Hook 扩展 (Backwards-Compatible)：**
```python
# V1.0.6: 新增 descriptor 参数, 但 stage_name 保留
# Pipeline.run() 同时传 stage_name + descriptor
def before_stage(
    ctx,
    stage_name: str,                    # V1.0.5 兼容
    descriptor: Optional[StageDescriptor] = None,  # V1.0.6 新增
): ...
```

- ✅ V1.0.5 旧 Hook 不传 `descriptor` 仍可工作（默认值 None）
- ✅ V1.0.6 新 Hook 可用 `descriptor.capabilities` / `descriptor.role` 做决策
- ✅ 签名向后兼容

### 2.5 Stage 角色 (Role) 枚举

V1.0.6 引入语义角色（基于 ChatGPT 9.93/10 路线图）：

| Role | Stage | 说明 |
|------|-------|------|
| `"stage"` | RouteStage | 通用 stage |
| `"metric"` | MetricsStage | 收集 metrics |
| `"retry"` | RetryStage | 重试 |
| `"checkpoint"` | CheckpointStage | 持久化 |
| `"condition"` | ConditionStage | 流程控制 |

未来 V2 可加：`"auth"` / `"rate_limit"` / `"cache"` / `"transform"` 等。

### 2.6 兼容旧 Stage (V1.0.x 兼容)

V1.0.6 仍允许 Stage 不实现 `descriptor`（保持 V1.0.5 行为）：

```python
class CustomStage:
    """V1.0.6: 无 descriptor 的 Stage (兼容 V1.0.x)."""
    name = "custom"  # V1.0.5 行为

    def __call__(self, ctx):
        ...
```

`Pipeline.run()` 检测：
- 如果 Stage 有 `descriptor` 属性 → 用 Descriptor
- 如果 Stage 只有 `name` 属性 → 用 `StageDescriptor(name=stage.name)` 默认 Descriptor

```python
# V1.0.6 Pipeline.run() 兼容逻辑
def _get_descriptor(stage) -> StageDescriptor:
    """V1.0.6: 提取 Stage 的 Descriptor, 兼容 V1.0.x Stage."""
    if hasattr(stage, "descriptor") and isinstance(stage.descriptor, StageDescriptor):
        return stage.descriptor
    # V1.0.x 兼容: 默认 Descriptor
    name = getattr(stage, "name", "stage")
    return StageDescriptor(name=name)
```

---

## 3. 关键决策

### 3.1 为什么 `dataclass(frozen=True)`？

- ✅ 不可变：Descriptor 是元数据，不应被运行时修改
- ✅ 可哈希：未来 Registry / Set 友好
- ✅ 类型安全：字段访问有类型提示

### 3.2 为什么不用 Enum 而用字符串 role？

- ✅ 向后兼容：V1.0.x Stage 可自定义 role
- ✅ 简单：无需 `class Role(str, Enum)` 包装
- ✅ V2 可加 Enum layer 做校验

### 3.3 为什么 `descriptor` 是 ClassVar 而非 instance attr？

- ✅ 同一 Stage 类的所有实例共享同一 Descriptor
- ✅ 节省内存
- ✅ 不可变 (frozen=True) 保证安全

### 3.4 为什么 `always_run_after_stop` 是关键字段？

来自 V1.0.4 ChatGPT 9.95/10 关键采纳：

> "Checkpoint 总是写 (即使 abort)"
> 移除 `ctx.stop` 短路

V1.0.6 把这个语义显式化：`always_run_after_stop=True` 表明此 Stage 必须在 stop 路径也执行。

### 3.5 为什么 Hook 签名只加 `descriptor` 参数而不改 stage_name？

- ✅ V1.0.5 Hook API 已 Approved (9.93/10)
- ✅ Backwards-compatible
- ✅ 旧 Hook 不需修改

---

## 4. 替代方案

### 4.1 替代 1：Stage 继承自 `Stage` 基类（强制继承）

- ❌ 破坏 V1.0.5 API（V1.0.5 接受 callable 任意对象）
- ❌ V1.0.5 Hook 测试中 `class CustomStage` 不继承任何基类
- ✅ 本 ADR 允许不继承（默认 Descriptor 兜底）

### 4.2 替代 2：Stage Registry（V2 注册表）

- ❌ 引入全局状态
- ❌ V1.0.6 范围太大
- ✅ V2 评估

### 4.3 替代 3：保留字符串约定

- ❌ 重复 ChatGPT 9.93/10 已识别的脆弱性
- ❌ V1.0.4 CheckpointStage 唯一耦合未消除

### 4.4 替代 4：Protocol / ABC 抽象

- ❌ Stage 行为签名稳定（V1.0.1 已定）
- ❌ Descriptor 才是元数据抽象的正确层
- ✅ 本 ADR 用 dataclass 表达元数据

---

## 5. 影响范围

### 5.1 改动的文件

| 文件 | 改动 |
|------|------|
| `planner/stage_descriptor.py` (NEW) | StageDescriptor dataclass + 默认工厂 |
| `planner/stages/route_stage.py` | 加 `descriptor` ClassVar |
| `planner/stages/metrics_stage.py` | 加 `descriptor` ClassVar |
| `planner/stages/retry_stage.py` | 加 `descriptor` ClassVar |
| `planner/stages/checkpoint_stage.py` | 加 `descriptor` ClassVar (含 `always_run_after_stop=True`) |
| `planner/stages/condition_stage.py` | 加 `descriptor` ClassVar |
| `planner/pipeline.py` | `Pipeline.run()` 用 `descriptor.always_run_after_stop` 替代字符串识别 |
| `planner/hooks.py` | Hook 签名加 `descriptor` 可选参数 (Backwards-compat) |
| `tests/test_stage_descriptor.py` (NEW) | StageDescriptor 单元测试 |
| `tests/test_pipeline.py` | 增量测试 V1.0.6 Pipeline 行为 |
| `tests/test_pipeline_hooks.py` | 增量测试 V1.0.6 Hook descriptor 参数 |
| `docs/runtime-contract.md` | 同步 §9.1 Stage Descriptor 段 |

### 5.2 兼容性保证

- ✅ V1.0.x Stage 不实现 `descriptor` 仍可工作（默认 Descriptor 兜底）
- ✅ V1.0.5 Hook 签名仍可工作（`descriptor` 默认 None）
- ✅ 公共 API (`Pipeline.run()` / `default_pipeline()`) 签名不变
- ✅ `ctx` / `Result` / `ExecutionStore` 接口不变

### 5.3 Core Freeze 影响

- ❌ **不**改 `core/` 下任何文件
- ❌ **不**改 `router/router.py`
- ❌ **不**改 `providers/`
- ✅ 仅 `planner/` 内扩展

---

## 6. 测试策略

### 6.1 StageDescriptor 单元测试 (10+)

- `test_default_descriptor` — 默认值
- `test_frozen` — 不可变
- `test_equality` — dataclass eq
- `test_hashable` — 可哈希 (Set/字典)
- `test_capabilities_set` — capabilities 是 Set
- `test_always_run_after_stop_default_false` — 默认 False
- `test_role_default_stage` — 默认 role="stage"
- `test_experimental_default_false` — 默认 False
- `test_idempotent_default_true` — 默认 True
- `test_custom_descriptor` — 自定义字段

### 6.2 Pipeline 集成测试 (5+)

- `test_pipeline_uses_descriptor_not_name` — 验证 Pipeline 不再依赖 `stage.name`
- `test_checkpoint_runs_after_stop_via_descriptor` — 通过 `always_run_after_stop=True` 触发
- `test_old_stage_without_descriptor_compat` — V1.0.x Stage 仍可工作
- `test_descriptor_renamed_stage_still_works` — Stage 重命名不影响 Pipeline
- `test_pipeline_with_experimental_stage_logs_warning` — experimental Stage 触发日志

### 6.3 Hook 兼容性测试 (3+)

- `test_old_hook_without_descriptor_param_works` — V1.0.5 Hook 不传 `descriptor` 仍 OK
- `test_new_hook_with_descriptor_works` — V1.0.6 Hook 收到 descriptor
- `test_hook_can_decide_based_on_descriptor_capabilities` — Hook 基于 capabilities 决策

---

## 7. 实施计划

### 7.1 阶段 1: StageDescriptor 基础 (Day 1)
- `planner/stage_descriptor.py` (NEW)
- `tests/test_stage_descriptor.py` (NEW)
- 10+ 单元测试通过

### 7.2 阶段 2: Stage 集成 (Day 1-2)
- 5 个 Stage 加 `descriptor` ClassVar
- Pipeline.run() 改用 `descriptor.always_run_after_stop`
- 兼容性测试通过

### 7.3 阶段 3: Hook 演进 (Day 2)
- Hook 签名加 `descriptor` 可选参数
- Pipeline.run() 传 `descriptor` 给 Hook
- Hook 兼容性测试通过

### 7.4 阶段 4: 全量回归 (Day 2)
- V1.0.x 全量测试 (152+ 测试)
- Runtime Contract 同步
- ChatGPT 代码审核

---

## 8. ChatGPT 审核请求

> **本 ADR 草案的关键问题 (待 ChatGPT 评审):**
>
> 1. **StageDescriptor 字段集**：name / version / role / capabilities / idempotent / has_side_effects / always_run_after_stop / experimental / description / owner — 是否过宽或过窄？哪些 V1.0.6 必须，哪些 V2？
>
> 2. **Pipeline 解耦深度**：用 `descriptor.always_run_after_stop` 替代 `stage.name == "checkpoint"` 是否充分？是否还要加 `descriptor.role == "checkpoint"` 二次检查？
>
> 3. **Hook 签名扩展**：加 `descriptor: Optional[StageDescriptor] = None` 是否正确？是否应该用 `**kwargs` 避免签名膨胀？
>
> 4. **Stage 基类选择**：本 ADR 引入 `Stage` 基类但不强求继承。是否应该用 `Protocol` 表达 Stage 接口？是否应该完全不强求 Descriptor 属性（用更智能的 `_get_descriptor` 工厂）？
>
> 5. **`role` 字符串 vs Enum**：V1.0.6 用字符串 `role`，V2 转 Enum。是否正确？是否应直接 Enum + str？
>
> 6. **Capabilities 集合 vs 列表**：`Set[str]` 而非 `List[str]`，避免重复。是否合理？
>
> 7. **V1.0.x 兼容性测试**：旧 Stage 无 `descriptor` 时默认 `StageDescriptor(name=stage.name)` — 这是否会让 V1.0.4 CheckpointStage 的 `always_run_after_stop` 默认 False 而破坏 abort-after-checkpoint？
>
> 8. **测试覆盖**：10 + 5 + 3 测试是否足够？是否需要额外的 stress test / property-based test？
>
> 9. **Runtime Contract 同步**：§9.1 Stage Descriptor 段如何写？是否需要独立的 `docs/stage-descriptor.md`？
>
> 10. **V1.0.7 Runtime Metadata Schema 统一** 是否应在本 ADR 一起做（避免 V1.0.6 命名空间冲突）？

**期望评分：9.5+/10**

---

## 9. V1.0.5 → V1.0.6 演化图

```
V1.0.5:
  Pipeline.run()
    └─ if stage.name == "checkpoint" and hasattr(stage, "store"):  ← 字符串 + duck typing

V1.0.6:
  Pipeline.run()
    └─ if stage.descriptor.always_run_after_stop:                  ← Descriptor 字段
        └─ Hook 收到 descriptor (可选)
```

**关键演进：**
- 字符串约定 → 类型安全
- 单一识别点 → 统一 Descriptor
- Hook 拿不到元数据 → Hook 收到 Descriptor
- V1.0.4 CheckpointStage 唯一耦合 → 完全消除
- V2 StageDescriptor 路线图 → V1.0.6 落地

---

## 10. 关联

- **前序**: [ADR-0025 PipelineHooks](0025-pipeline-hooks.md) (V1.0.5 Accepted 9.93/10)
- **后续**: V1.0.7 Runtime Metadata Schema 统一 (ChatGPT 路线图)
- **V2 路线**: Stage Registry / Schema validation / 自动文档生成
- **Runtime Contract**: §9.1 (Stage Descriptor 段待写)
- **ARCHITECTURE**: §2.3 V1.0 路线 (Stage 层)

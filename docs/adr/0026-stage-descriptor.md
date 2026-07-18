# ADR-0026: StageDescriptor — Stage 元数据描述对象 (V1.0.6)

- **里程碑**: V1.0.6
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: **Accepted** ([ChatGPT 9.94/10 APPROVED](../reviews/0026-adr-chatgpt-review.md), 1 Critical + 2 Non-blocking 全部采纳)
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0023 CheckpointStage](0023-checkpoint-stage.md), [ADR-0024 ConditionStage](0024-condition-stage.md), [ADR-0025 PipelineHooks](0025-pipeline-hooks.md)
- **后续**: V1.0.7 ADR-0027 Runtime Metadata Schema 统一
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

### 2.2 Stage 接口 (Protocol, 非继承要求)

**ChatGPT 9.94/10 Q4 采纳：改 `class Stage` 基类为 `Protocol`。原因：当前架构刻意避免继承，Stage 已用 structural typing。Protocol 保留这一哲学。**

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Stage(Protocol):
    """Stage 接口约定 (V1.0.6 Protocol, 非继承要求).

    任何满足此协议的对象都是 Stage (duck typing + Protocol 验证).
    """
    descriptor: StageDescriptor

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext: ...


class RouteStage:
    """V1.0.6: 不继承 Stage, 仅满足 Protocol."""
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


class MetricsStage:
    descriptor = StageDescriptor(
        name="metrics",
        version=1,
        role="metric",
        capabilities={"collects_metrics"},
        idempotent=True,
        has_side_effects=False,
        description="Collects per-stage metrics",
    )

    def __call__(self, ctx):
        ...


class RetryStage:
    descriptor = StageDescriptor(
        name="retry",
        version=1,
        role="retry",
        capabilities={"retries"},
        idempotent=False,  # 重试 -> 多次副作用
        has_side_effects=True,
        description="Retries failed bridge execution",
    )

    def __call__(self, ctx):
        ...


class CheckpointStage:
    """V1.0.6: 显式 descriptor, 关键字段 always_run_after_stop=True (V1.0.4 ChatGPT 9.95/10 采纳)."""
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

    def __call__(self, ctx):
        ...


class ConditionStage:
    """V1.0.6: 显式 descriptor."""
    descriptor = StageDescriptor(
        name="condition",
        version=1,
        role="condition",
        capabilities={"controls_flow"},
        idempotent=True,
        has_side_effects=False,
        description="Conditional branch: continue / skip / abort",
    )

    def __call__(self, ctx):
        ...
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

### 2.6 兼容旧 Stage (V1.0.x 兼容 + Critical 迁移要求)

**ChatGPT 9.94/10 Q7 Critical 调整：所有 built-in Stage 必须显式定义 `descriptor`。**

**关键问题：** 默认 `StageDescriptor(name=stage.name)` 兜底会丢 `always_run_after_stop=True`（CheckpointStage 关键字段），静默破坏 V1.0.4 语义。

**解决方案：**
1. **强制迁移规则 (Critical)：** 所有 ADR-0026 之前引入的 built-in Stage 必须在 V1.0.6 实施时**显式定义 `descriptor`**。
2. **兼容性 helper 仅给 user plugin / legacy extension。** 绝不推断 checkpoint 语义（不再 `hasattr(stage, "store")` 探测）。
3. **不接受 Option B（hasattr duck typing）：** 那会重新引入 ADR-0026 试图消除的字符串约定。

```python
# V1.0.6 get_descriptor() — 仅给 user plugin / legacy
def get_descriptor(stage) -> StageDescriptor:
    """V1.0.6: 提取 Stage Descriptor, 兼容 V1.0.x 旧 Stage.

    关键约束 (ChatGPT 9.94/10 Q7):
      - built-in Stage 全部显式 descriptor, 此 helper 仅给:
        * user plugin
        * legacy extension (V1.0.5 之前用户自定义的 Stage)
      - 绝不推断 checkpoint 语义 (不再 hasattr(stage, "store") 探测).
      - 绝不基于 stage.name 字符串识别角色.
    """
    if hasattr(stage, "descriptor") and isinstance(stage.descriptor, StageDescriptor):
        return stage.descriptor
    name = getattr(stage, "name", "stage")
    # V1.0.6: 默认 Descriptor (兜底)
    return StageDescriptor(name=name)
```

**V1.0.6 实施时的迁移清单：**

| Stage | 必须显式 descriptor | 关键字段 |
|-------|---------------------|----------|
| `RouteStage` | ✅ | `role="stage"` |
| `MetricsStage` | ✅ | `role="metric"` |
| `RetryStage` | ✅ | `role="retry"`, `idempotent=False` |
| `CheckpointStage` | ✅ | `role="checkpoint"`, **`always_run_after_stop=True`** (V1.0.4 关键) |
| `ConditionStage` | ✅ | `role="condition"`, `idempotent=True` |

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

V1.0.6 把这个语义显式化：`always_run_after_stop=True` 表明此 Stage 必须在 stop 路径也执行。**这是 V1.0.6 Critical 迁移要求的核心字段**（§2.6）。

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

### 6.1 StageDescriptor 单元测试 (12+)

- `test_default_descriptor` — 默认值
- `test_frozen` — 不可变 (ChatGPT 9.94/10 Q8 采纳: `descriptor.role = ...` 抛 FrozenInstanceError)
- `test_frozen_cannot_set_role` — 不可变 (Q8 采纳)
- `test_equality` — dataclass eq
- `test_hashable` — 可哈希 (Set/字典)
- `test_capabilities_set` — capabilities 是 Set
- `test_always_run_after_stop_default_false` — 默认 False
- `test_role_default_stage` — 默认 role="stage"
- `test_experimental_default_false` — 默认 False
- `test_idempotent_default_true` — 默认 True
- `test_custom_descriptor` — 自定义字段
- `test_legacy_stage_gets_default_descriptor` — V1.0.x 旧 Stage 无 descriptor 时接收默认 Descriptor (ChatGPT 9.94/10 Q8 采纳)

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

## 8. ChatGPT 审核结果 (9.94/10 APPROVED)

**最终评分：9.94 / 10** (Verdict: APPROVED with 1 Critical + 2 Non-blocking 全部采纳)

**关键采纳：**

1. **Q7 Critical (采纳):** 所有 built-in Stage 必须显式定义 `descriptor`（见 §2.6 强制迁移清单）。`hasattr(stage, "store")` duck typing 被拒绝 — 那会重新引入 ADR-0026 试图消除的字符串约定。

2. **Q4 Non-blocking (采纳):** 改 `class Stage` 基类为 `@runtime_checkable Protocol`（见 §2.2）。原因：当前架构刻意避免继承，Stage 已用 structural typing。

3. **Q8 Non-blocking (采纳):** 加 2 项测试 — `test_frozen_cannot_set_role`（immutability）+ `test_legacy_stage_gets_default_descriptor`（legacy fallback）。

**保持不变 (Q1, Q2, Q3, Q5, Q6, Q9, Q10):**

- ✅ `always_run_after_stop` 单一行为信号（Q2 Behavior > taxonomy）
- ✅ `role` 保持字符串（Q5 V2 转 Enum）
- ✅ `capabilities` Set[str]（Q6 语义标签无重复）
- ✅ Hook 签名加 `descriptor` 可选参数（Q3 Optional typed > **kwargs）
- ✅ `capabilities` 保留 dataclass 但 Runtime Contract 不依赖（Q1 V2 Stage Registry 消费）
- ✅ Runtime Contract 同步在 ADR-0026 内（Q9 Registry/Plugin/UI 出现时再拆）

**V1.0.7 独立 ADR-0027 (采纳):** Runtime Metadata Schema 统一（condition_eval / server_metrics / stopped_by / future tracing）。StageDescriptor 答 "What is a Stage?"，Metadata 答 "What happened during execution?" — 不同概念。

**V2 路线 (Defer):** Stage Registry / Role Enum / Descriptor Validation。

完整审核记录：[docs/reviews/0026-adr-chatgpt-review.md](../reviews/0026-adr-chatgpt-review.md)。

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

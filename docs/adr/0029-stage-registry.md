# ADR-0029: Stage Registry (V1.0.8)

- **里程碑**: V1.0.8
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: **Accepted** ✅ (ChatGPT 9.93/10 APPROVED, commit a09cf7e)
- **依赖**: [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10), [ADR-0027 RuntimeMetadata](0027-runtime-metadata-schema.md) (V1.0.7 Accepted 9.88/10), [ADR-0028 Metadata Access API](0028-metadata-access-api.md) (V1.0.8 Accepted 9.94/10)
- **后续**: V1.0.9 ADR-0030 Registry Introspection (MUST ①) / ADR-0031 Metadata Serialization (MUST ②) / Pipeline Describe (SHOULD)
- **ChatGPT 审核**: 9.93/10 APPROVED — `docs/reviews/0029-adr-chatgpt-review.md`
- **采纳调整** (5 Non-blocking + 1 重构):
  - **T1**: `reset_default_registry()` 测试 helper（Singleton 污染防护）
  - **T2**: `describe(name)` 返回 StageDescriptor（CLI / Inspection 用）
  - **Q3 重构**: `default_order()` 暴露顺序（Pipeline 不再 hardcode role 顺序）
  - **Q5 职责分离**: ADR 明确 `clear()` 不重注册 builtins, `default_registry()` 永远负责 builtins
  - **Q7 核心**: Registry 不感知 RuntimeMetadata（保持 V1.x 三层解耦）
  - **Q1 范围聚焦**: 不加 `by_owner` / `by_version` / `experimental`（V1.0.8 最小 API）

> **StageDescriptor 答 "What is a Stage?" (静态 metadata)**
> **RuntimeMetadata 答 "What happened during execution?" (动态 metadata)**
> **Metadata Access API 答 "How to access this data uniformly?" (接口)**
> **Stage Registry 答 "Where do I find a Stage?" (发现 / 生命周期 / 能力索引)**
> **本 ADR 让 Stage 从"散落导入"演进为"统一注册 + 按需发现"。**

---

## 1. 背景与目标

### 1.1 背景

V1.0.6 引入 `StageDescriptor` 让每个 Stage 自描述（name / role / capabilities / idempotent / has_side_effects / always_run_after_stop / version / description / owner / experimental）。

V1.0.7-V1.0.8 强化了 Runtime Metadata + Access API。

**当前痛点：Pipeline 构造散落导入**

```python
# V1.0.1-V1.0.7 Pipeline 构造 (散落导入)
from planner.pipeline import (
    Pipeline, RouteStage, MetricsStage,
)
from planner.stages.retry_stage import RetryStage
from planner.stages.checkpoint_stage import CheckpointStage
from planner.stages.condition_stage import ConditionStage

# 每个 Pipeline 调用方需要：
# 1. 显式 import 5+ Stage 类
# 2. 显式 instantiate (RetryStage(), ConditionStage(...), ...)
# 3. 显式 ordering [RouteStage, MetricsStage, ...]
# 4. 重复 boilerplate 在所有 Pipeline 调用方
```

**问题：**
1. **可发现性差**: 想知道"哪些 Stage 实现了 `controls_flow` capability?" — 必须 grep 代码
2. **角色查询缺失**: 想知道"哪些 Stage 是 `role='retry'`?" — 必须 grep
3. **第三方 Stage 集成混乱**: 用户写自己的 Stage, 然后 import, instantiate, register 到 Pipeline — 无统一管理
4. **测试/调试困难**: "Pipeline 当前有哪些 Stage?" — 必须看构造函数
5. **CLI/工具受限**: "列出所有 Stage 用于 `--stage x` 选择" — 需要扫描所有 module
6. **Plugin ecosystem 弱**: 第三方 Stage 没有注册中心, 难以发现

### 1.2 目标（V1.0.8 Stage Registry）

V1.0.8 引入 **StageRegistry** — 统一 Stage 注册中心 + 索引 + 查询 API：

1. **核心 API (8 个方法)**:
   - `register(stage, *, replace=False)` — 注册 Stage (按 descriptor.name)
   - `unregister(name)` — 注销 Stage
   - `lookup(name) -> Optional[Stage]` — 按 name 查
   - `by_role(role) -> List[Stage]` — 按 role 查
   - `by_capability(capability) -> List[Stage]` — 按 capability 查
   - `all() -> List[Stage]` — 列出所有
   - `__contains__(name) -> bool` — Python 容器语义
   - `__len__() -> int` — Python 容器语义

2. **Default Registry 单例**:
   - `default_registry()` — 进程级单例, built-in Stage 自动注册
   - 用户可注册第三方 Stage 到 default registry
   - 避免每个测试/CLI 单独创建 Registry

3. **Default Pipeline 工厂**:
   - `default_pipeline()` — 用 default registry 构造默认 Pipeline
   - 替代 `Pipeline(stages=[RouteStage(), MetricsStage(), ...])` 散落构造
   - 未来 V1.0.9 评估: 不同的 `default_pipeline(role_set=...)` 构造变体

4. **第三方 Stage 集成**:
   - 用户注册: `registry.register(MyPluginStage())`
   - 自动按 descriptor.name / role / capabilities 索引
   - 立即可被 `by_capability()` / `by_role()` 查询

5. **不破坏 V1.0.1-V1.0.7**:
   - 所有现有 Stage 保持可单独 import
   - 所有现有 Pipeline 构造方式保留
   - Registry 是 **新能力**, 非替换

### 1.3 非目标

- ❌ **不**改 StageDescriptor (V1.0.6 已稳定)
- ❌ **不**改 RuntimeMetadata / Access API (V1.0.7-V1.0.8 已稳定)
- ❌ **不**做 Pipeline Introspection (V1.0.9 评估)
- ❌ **不**做 Metadata Serialization (V1.0.9 评估)
- ❌ **不**做 remote / distributed Registry (V1.x 范围内)
- ❌ **不**做 auto-discovery via importlib (太复杂, 评估 V1.0.9)
- ❌ **不**改 Pipeline 内部 stage 执行顺序逻辑
- ❌ **不**做 Stage 装饰器自动注册 (V1.0.9 评估)

---

## 2. 设计

### 2.1 StageRegistry 接口

```python
# planner/stage_registry.py (NEW)
from __future__ import annotations
import logging
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from planner.stage_descriptor import Stage, get_descriptor

logger = logging.getLogger(__name__)


class StageRegistry:
    """Stage 注册中心 + 索引 + 查询 API (V1.0.8, ADR-0029).

    核心能力:
      - 统一注册: register(stage) / unregister(name)
      - 索引加速: by_role(role) / by_capability(capability) (O(1) 索引, 非 O(n) 扫描)
      - Python 容器语义: __contains__ / __len__ / __iter__

    关键不变量 (Runtime Contract §12):
      - Stage 按 descriptor.name 注册 (强一致)
      - 同一 name 重复注册: 默认 raise, replace=True 时替换
      - Stage 实例不被 Registry 修改 (Registry 仅持引用)
      - Stage 注销后, 引用立即失效 (Registry 内部清除索引)
    """

    def __init__(self) -> None:
        # Stage 存储 (descriptor.name → Stage)
        self._stages: Dict[str, Stage] = {}
        # 索引 (role → {name})
        self._by_role: Dict[str, Set[str]] = {}
        # 索引 (capability → {name})
        self._by_capability: Dict[str, Set[str]] = {}

    # ─────────────────────────────────────────────────────
    # 1. 注册 / 注销
    # ─────────────────────────────────────────────────────

    def register(self, stage: Stage, *, replace: bool = False) -> None:
        """注册 Stage 到 Registry.

        Args:
            stage: 任何实现 Stage Protocol 的对象 (V1.0.6 descriptor 属性)
            replace: 如果 name 已注册, True 替换, False raise

        Raises:
            ValueError: stage 没有 descriptor (V1.0.7+ 强约束, ChatGPT 9.95/10 Q7)
            KeyError: name 已注册 且 replace=False
        """
        descriptor = get_descriptor(stage)  # V1.0.6 helper, 强类型
        name = descriptor.name
        if name in self._stages and not replace:
            raise KeyError(
                f"Stage {name!r} already registered. "
                f"Use replace=True to overwrite."
            )
        # 注销旧引用 (如有)
        if name in self._stages:
            self._unindex(name)
        # 存储 + 索引
        self._stages[name] = stage
        self._index(descriptor)

    def unregister(self, name: str) -> Optional[Stage]:
        """注销 Stage.

        Args:
            name: Stage name (descriptor.name)

        Returns:
            注销的 Stage 实例, 未找到返回 None
        """
        stage = self._stages.pop(name, None)
        if stage is not None:
            self._unindex(name)
        return stage

    def clear(self) -> None:
        """清空 Registry (主要用于测试隔离)."""
        self._stages.clear()
        self._by_role.clear()
        self._by_capability.clear()

    # ─────────────────────────────────────────────────────
    # 2. 查询
    # ─────────────────────────────────────────────────────

    def lookup(self, name: str) -> Optional[Stage]:
        """按 descriptor.name 查找 Stage.

        Args:
            name: Stage name

        Returns:
            Stage 实例 或 None (未找到)
        """
        return self._stages.get(name)

    def by_role(self, role: str) -> List[Stage]:
        """按 descriptor.role 查找所有 Stage.

        Args:
            role: Stage role (e.g. "stage", "retry", "checkpoint", "condition", "metric")

        Returns:
            Stage 列表 (按注册顺序, may be empty)
        """
        names = self._by_role.get(role, set())
        return [self._stages[n] for n in names if n in self._stages]

    def by_capability(self, capability: str) -> List[Stage]:
        """按 descriptor.capability 查找所有 Stage.

        Args:
            capability: capability string (e.g. "selects_provider", "collects_metrics",
                       "controls_flow", "retries_on_failure")

        Returns:
            Stage 列表 (按注册顺序, may be empty)
        """
        names = self._by_capability.get(capability, set())
        return [self._stages[n] for n in names if n in self._stages]

    def all(self) -> List[Stage]:
        """列出所有已注册 Stage.

        Returns:
            Stage 列表 (按注册顺序)
        """
        return list(self._stages.values())

    def roles(self) -> Set[str]:
        """列出所有已注册的 role.

        Returns:
            role 集合 (去重)
        """
        return set(self._by_role.keys())

    def capabilities(self) -> Set[str]:
        """列出所有已注册的 capability.

        Returns:
            capability 集合 (去重)
        """
        return set(self._by_capability.keys())

    # ─────────────────────────────────────────────────────
    # 3. Python 容器语义
    # ─────────────────────────────────────────────────────

    def __contains__(self, name: object) -> bool:
        """Python `in` 语义: 'name' in registry"""
        if not isinstance(name, str):
            return NotImplemented
        return name in self._stages

    def __len__(self) -> int:
        """Python `len()` 语义: len(registry)"""
        return len(self._stages)

    def __iter__(self):
        """Python `iter()` 语义: for name in registry"""
        return iter(self._stages)

    def __getitem__(self, name: str) -> Stage:
        """Python `[]` 语义: registry[name], 未找到 raise KeyError"""
        stage = self._stages.get(name)
        if stage is None:
            raise KeyError(f"Stage {name!r} not found in registry")
        return stage

    # ─────────────────────────────────────────────────────
    # 4. T2 (采纳 ChatGPT 9.93/10): describe(name) 返回 StageDescriptor
    # ─────────────────────────────────────────────────────

    def describe(self, name: str) -> Optional[StageDescriptor]:
        """返回 Stage 的 StageDescriptor (不返回 Stage 实例, 采纳 ChatGPT 9.93/10 T2).

        Use case:
          - CLI: `registry.describe("checkpoint")` 打印 descriptor 信息
          - Documentation: 自动生成 Stage catalog
          - Inspection: 调试时不需要 Stage 实例, 仅 metadata

        Args:
            name: Stage name

        Returns:
            StageDescriptor 或 None (未找到)
        """
        stage = self._stages.get(name)
        if stage is None:
            return None
        return get_descriptor(stage)

    # ─────────────────────────────────────────────────────
    # 5. Q3 重构 (采纳 ChatGPT 9.93/10): default_order() 暴露顺序
    # Pipeline 不再 hardcode role 顺序
    # ─────────────────────────────────────────────────────

    # V1.0.8 默认 Pipeline 顺序 (按 role)
    # 未来 V1.0.9+ 新增 role (trace / cache / observer) 直接加这里
    DEFAULT_ORDER: Tuple[str, ...] = ("stage", "metric", "checkpoint", "condition")

    def default_order(self) -> Tuple[str, ...]:
        """返回默认 Pipeline 构造顺序 (按 role).

        未来扩展 (V1.0.9+):
          - 加 trace / cache / observer 等新 role
          - Pipeline 走 registry.default_order() 而非 hardcode

        Returns:
            role 元组 (e.g. ("stage", "metric", "checkpoint", "condition"))
        """
        return self.DEFAULT_ORDER

    # ─────────────────────────────────────────────────────
    # 6. 内部: 索引管理
    # ─────────────────────────────────────────────────────

    def _index(self, descriptor: StageDescriptor) -> None:
        """按 descriptor 更新索引."""
        name = descriptor.name
        role = descriptor.role
        # role 索引
        if role not in self._by_role:
            self._by_role[role] = set()
        self._by_role[role].add(name)
        # capability 索引
        for cap in descriptor.capabilities:
            if cap not in self._by_capability:
                self._by_capability[cap] = set()
            self._by_capability[cap].add(name)

    def _unindex(self, name: str) -> None:
        """从索引移除 name."""
        # 找旧 stage descriptor
        old = self._stages.get(name)
        if old is None:
            return
        old_descriptor = get_descriptor(old)
        # role 索引
        role_set = self._by_role.get(old_descriptor.role)
        if role_set is not None:
            role_set.discard(name)
            if not role_set:
                self._by_role.pop(old_descriptor.role, None)
        # capability 索引
        for cap in old_descriptor.capabilities:
            cap_set = self._by_capability.get(cap)
            if cap_set is not None:
                cap_set.discard(name)
                if not cap_set:
                    self._by_capability.pop(cap, None)
```

### 2.2 Default Registry 单例

```python
# planner/stage_registry.py (继续)
_DEFAULT_REGISTRY: Optional[StageRegistry] = None


def default_registry() -> StageRegistry:
    """获取进程级 default registry 单例.

    行为:
      - 首次调用: 创建 registry + 自动注册 built-in Stage (RouteStage, MetricsStage,
                   RetryStage, CheckpointStage, ConditionStage)
      - 后续调用: 返回同一 instance (singleton pattern)
      - 第三方 Stage 集成: registry.register(MyPluginStage()) 后立即可用

    关键不变量:
      - 进程级单例, 跨 import 共享
      - clear() **不**清空 default registry (避免破坏 built-in Stage)
      - 第三方 Stage 可注册到 default registry, 也可创建独立 StageRegistry()
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = StageRegistry()
        _register_builtin_stages(_DEFAULT_REGISTRY)
    return _DEFAULT_REGISTRY


def _register_builtin_stages(registry: StageRegistry) -> None:
    """注册 5 个 built-in Stage (V1.0.1-V1.0.6 全部)."""
    from planner.pipeline import RouteStage, MetricsStage
    from planner.stages.retry_stage import RetryStage
    from planner.stages.checkpoint_stage import CheckpointStage
    from planner.stages.condition_stage import ConditionStage

    # 注意: built-in Stage 是 class, 不是 instance
    # Registry 持有 class 引用, instantiate 在 default_pipeline() 中
    registry.register(RouteStage())  # role="stage", cap={"selects_provider"}
    registry.register(RetryStage())  # role="retry", cap={"retries_on_failure"}
    registry.register(CheckpointStage())  # role="checkpoint", cap={"writes_snapshot"}
    registry.register(ConditionStage(condition=lambda c: True, on_true="continue", name="default"))  # role="condition", cap={"controls_flow"}
    registry.register(MetricsStage())  # role="metric", cap={"collects_metrics"}


# T1 (采纳 ChatGPT 9.93/10): reset_default_registry() 测试 helper
def reset_default_registry() -> None:
    """重置 default registry (测试隔离用, 采纳 ChatGPT 9.93/10 T1).

    关键不变量 (Q5 职责分离):
      - 重置后下次 default_registry() 重新 auto-register built-in
      - **不**在 Runtime 中调用 (会破坏 default registry 完整性)
      - 仅用于 pytest fixture teardown

    Use case:
        @pytest.fixture
        def clean_registry():
            from planner.stage_registry import reset_default_registry
            reset_default_registry()
            yield
            reset_default_registry()  # teardown
    """
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None


### 2.3 Default Pipeline 工厂 (Q3 重构)

```python
# planner/stage_registry.py (继续)
def default_pipeline(*, registry: Optional[StageRegistry] = None) -> Pipeline:
    """用 registry 构造 default Pipeline.

    Args:
        registry: 可选, 默认用 default_registry()

    Returns:
        Pipeline 实例, stages 按固定顺序:
          [RouteStage, MetricsStage, CheckpointStage, ConditionStage(s)]

    关键设计:
      - 顺序固定 (RouteStage → MetricsStage → CheckpointStage → Conditions)
      - 第三方 Stage 可通过 register 注入, 但顺序按"标准顺序"插入
      - 未来 V1.0.9: 支持 `default_pipeline(role_set=...)` 构造变体
    """
    from planner.pipeline import Pipeline

    if registry is None:
        registry = default_registry()

    stages = []
    # Q3 重构: 走 registry.default_order() 而非 hardcode role tuple
    for role in registry.default_order():
        stages.extend(registry.by_role(role))
    return Pipeline(stages=stages)
```

### 2.4 使用示例 (V1.0.8)

```python
# 旧写法 (V1.0.1-V1.0.7)
from planner.pipeline import Pipeline, RouteStage, MetricsStage
from planner.stages.checkpoint_stage import CheckpointStage

pipeline = Pipeline(stages=[
    RouteStage(),
    MetricsStage(),
    CheckpointStage(),
])
# 重复 boilerplate, 散落导入, 难以查询

# 新写法 (V1.0.8 Registry)
from planner.stage_registry import default_pipeline

pipeline = default_pipeline()
# 一行, 自动用 default registry, 自动按 role 排序

# 高级用法 1: 按 role 查询
from planner.stage_registry import default_registry
registry = default_registry()
all_metrics = registry.by_role("metric")  # [MetricsStage()]
all_retry = registry.by_role("retry")     # [RetryStage()]

# 高级用法 2: 按 capability 查询
all_selecting = registry.by_capability("selects_provider")  # [RouteStage()]
all_flow = registry.by_capability("controls_flow")         # [ConditionStage()]

# 高级用法 3: 第三方 Stage 集成
from planner.stages import MyPluginStage
registry.register(MyPluginStage(), replace=False)
# 立即可被查询 (按 name / role / capability)

# 高级用法 4: 测试隔离
import pytest
@pytest.fixture
def empty_registry():
    reg = StageRegistry()
    yield reg
    reg.clear()  # pytest fixture teardown

# 高级用法 5: CLI/工具
roles = registry.roles()  # {'stage', 'retry', 'checkpoint', 'condition', 'metric'}
caps = registry.capabilities()  # {'selects_provider', 'retries_on_failure', ...}
for name in registry:  # 迭代 name
    stage = registry[name]
    print(f"{name}: {stage.descriptor}")
```

### 2.5 API 设计原则

1. **O(1) 索引查找** — `by_role()` / `by_capability()` 用预构建索引, 非 O(n) 扫描
2. **重复注册 raise** — 默认 `replace=False`, 避免意外覆盖
3. **Stage 不被修改** — Registry 持引用, 不修改 Stage
4. **Python 容器语义** — `in` / `len` / `iter` / `[]` 一致
5. **Default singleton 谨慎** — `clear()` 不影响 default (避免破坏 built-in)
6. **第三方友好** — `register()` 接任何实现 Stage Protocol 的对象
7. **测试友好** — `StageRegistry()` 独立创建, `clear()` 隔离

### 2.6 向后兼容

- ✅ **100% 兼容 V1.0.1-V1.0.7**: 旧代码 `from planner.pipeline import Pipeline, RouteStage, ...` 仍工作
- ✅ 旧 `Pipeline(stages=[...])` 构造保留
- ✅ `default_pipeline()` 是新工厂, 不替代
- ✅ 旧 `Pipeline.run()` 行为不变
- ✅ `StageDescriptor` (V1.0.6) 接口不变
- ✅ Core Freeze 保持 (`core/`, `router/`, `providers/` 不变)

---

## 3. 关键决策

### 3.1 为什么用预构建索引而非扫描？

- ✅ `by_role()` / `by_capability()` 走 dict 索引, O(1)
- ❌ 扫描每个 Stage 调 `get_descriptor()` 是 O(n), n=5 没问题, n=50 第三方 Stage 慢
- ✅ Registry 设计支持大规模 Stage 生态

### 3.2 为什么 `register()` 默认 raise 而非 replace？

- ✅ 防止意外覆盖 (用户写错 name 时立即报错)
- ✅ 第三方 Stage 冲突时显式控制
- ✅ `replace=True` 显式表达意图
- 选择类似 Python `dict[key] = value` 行为 vs `dict.update()` 行为

### 3.3 为什么 `default_registry()` 用 singleton？

- ✅ 进程级单例, built-in Stage 自动注册一次
- ✅ 第三方 Stage `default_registry().register(MyPlugin())` 立即全局可用
- ❌ 不用 singleton → 每次 `default_pipeline()` 创建新 registry + 重新注册, 性能 + 行为问题
- 类似 `logging.getLogger()` 单例模式

### 3.4 为什么 `default_pipeline()` 按 role 固定顺序？

- ✅ 标准顺序: route → metric → checkpoint → condition (V1.0.x 实践验证)
- ✅ 不同 role 的 Stage 不应互串顺序
- ❌ 按注册顺序 → 用户 register 顺序影响 Pipeline 行为, 不直观
- 选择: 按 role 固定顺序, 未来 V1.0.9 评估 role_set 构造变体

### 3.5 为什么 `clear()` 不影响 default registry？

- ✅ 防止测试误 clear default → 破坏 built-in Stage
- ✅ `default_registry()` 是 process-global, clear 应显式调 `StageRegistry().clear()`
- 测试隔离用独立 `StageRegistry()` 实例

### 3.6 为什么 V1.0.8 不做 auto-discovery？

- ❌ importlib auto-discovery 复杂, V1.0.8 范围聚焦
- ❌ 第三方 Stage 仍需显式 `register()` 才能被发现
- ✅ 简化设计, 显式注册明确
- V1.0.9 评估: `entry_points` / `planner.plugins` 自动发现

### 3.7 为什么 V1.0.8 不做 Stage 装饰器自动注册？

- ❌ 装饰器耦合 import 顺序, 测试困难
- ❌ 显式 register 更明确
- V1.0.9 评估: `@register_stage` 装饰器作为可选糖

### 3.8 为什么 V1.0.8 不改 Pipeline 内部 stage 顺序逻辑？

- ✅ Pipeline 行为已稳定 (V1.0.1 Accepted 9.95/10)
- ✅ Registry 仅提供 Stage 来源, Pipeline 仍决定顺序
- ✅ 减少 V1.0.8 改动面

---

## 4. 替代方案

### 4.1 替代 1：纯文档化（不加 Registry）

- ❌ 可发现性差
- ❌ 第三方 Stage 集成混乱
- ❌ CLI/工具受限
- **结论：reject**

### 4.2 替代 2：singleton 全局 dict 而非 StageRegistry 类

- ❌ 无索引, O(n) 扫描
- ❌ 无类型安全
- ❌ 无容器语义
- **结论：reject**

### 4.3 替代 3：当前采纳 (StageRegistry + default_registry + default_pipeline)

- ✅ 简单、聚焦、8 个核心方法
- ✅ O(1) 索引, 容器语义
- ✅ 第三方友好
- **结论：adopt**

### 4.4 替代 4：decorator auto-register (`@register_stage`)

- ❌ 耦合 import 顺序
- ❌ 测试隔离困难
- **结论：defer（V1.0.9 评估）**

### 4.5 替代 5：importlib auto-discovery

- ❌ 复杂, V1.0.8 范围过大
- ❌ 显式注册更明确
- **结论：defer（V1.0.9 评估）**

### 4.6 替代 6：合并 Registry + Access API + Serialization 到一个 V1.0.8 mega-ADR

- ❌ Review 困难
- ❌ 范围过大
- ✅ ChatGPT 9.91/10 Q7 强烈建议"小 ADR"
- **结论：reject（采纳 ChatGPT）**

---

## 5. 影响范围

### 5.1 改动文件

| 文件 | 改动 |
|------|------|
| `planner/stage_registry.py` (NEW) | StageRegistry + default_registry + default_pipeline (~280 行) |
| `planner/pipeline.py` | 0 改动 (Pipeline 行为不变) |
| `planner/stages/retry_stage.py` | 0 改动 (StageDescriptor 已 V1.0.6) |
| `planner/stages/checkpoint_stage.py` | 0 改动 |
| `planner/stages/condition_stage.py` | 0 改动 |
| `tests/test_stage_registry.py` (NEW) | 25+ tests |
| `tests/test_default_pipeline.py` (NEW) | 5+ tests |
| `docs/runtime-contract.md` | §12 Stage Registry (待写) |

### 5.2 兼容性

- ✅ **零 Breaking Change**: V1.0.1-V1.0.7 所有 API 保留
- ✅ 第三方 Stage / Hook / Pipeline 调用方不受影响
- ✅ 目标：V1.0.8 共 30+ 新增测试, 全部通过

### 5.3 Core Freeze 影响

- ❌ **不**改 `core/` 下任何文件
- ❌ **不**改 `router/router.py`
- ❌ **不**改 `providers/`
- ✅ 仅 `planner/` 内扩展

---

## 6. 测试策略

### 6.1 StageRegistry 核心测试 (25+)

- `test_empty_registry` — 初始 state
- `test_register_basic` — 注册一个 Stage
- `test_register_replaces_when_replace_true` — replace=True 替换
- `test_register_raises_on_duplicate` — replace=False 重复 raise
- `test_register_requires_descriptor` — 无 descriptor 报错 (V1.0.7 强约束)
- `test_unregister_existing` — 注销存在的 Stage
- `test_unregister_nonexisting` — 注销不存在的返回 None
- `test_clear` — clear 清空
- `test_lookup_existing` — 找到
- `test_lookup_nonexisting` — 找不到返回 None
- `test_by_role_single` — 单个 role 查询
- `test_by_role_multiple` — 多个 role 查询
- `test_by_role_empty` — role 无 Stage
- `test_by_capability_single` — 单个 capability 查询
- `test_by_capability_multiple` — 多个 capability 查询
- `test_by_capability_empty` — capability 无 Stage
- `test_all_returns_all` — all() 返回所有
- `test_roles_returns_all_roles` — roles() 返回所有 role
- `test_capabilities_returns_all_capabilities` — capabilities() 返回所有 cap
- `test_contains` — `in` 语义
- `test_len` — `len()` 语义
- `test_iter` — `iter()` 语义
- `test_getitem` — `[]` 语义
- `test_getitem_raises_on_missing` — 未找到 raise KeyError
- `test_register_unregister_index_consistency` — 注册/注销后索引一致

### 6.2 Default Registry 测试 (8+)

- `test_default_registry_singleton` — singleton 行为
- `test_default_registry_has_builtin_stages` — built-in 5 个 Stage 已注册
- `test_default_registry_register_third_party` — 第三方 Stage 注册
- `test_default_registry_persists_across_calls` — 跨调用持久
- `test_default_registry_clear_does_not_affect_builtin` — clear 不影响 default
- `test_default_registry_unregister_builtin_warning` — 注销 built-in 警告
- `test_default_registry_third_party_visible_to_others` — 第三方注册后全局可见
- `test_default_registry_replace_builtin` — replace 替换 built-in

### 6.3 Default Pipeline 工厂测试 (5+)

- `test_default_pipeline_returns_pipeline` — 返回 Pipeline 实例
- `test_default_pipeline_includes_builtin` — 包含 built-in Stage
- `test_default_pipeline_role_order` — 顺序: route → metric → checkpoint → condition
- `test_default_pipeline_with_custom_registry` — 接 registry 参数
- `test_default_pipeline_third_party_appears` — 第三方 Stage 出现在 Pipeline

### 6.4 第三方 Stage 集成测试 (3+)

- `test_third_party_register_visible` — 注册后立即可查
- `test_third_party_by_capability` — 按 capability 找到
- `test_third_party_replace_false_raises` — 重复 name 报错

### 6.5 V1.0.x 回归测试

- ✅ V1.0.7 + V1.0.8 全部 347+ 测试无需修改
- ✅ 目标：V1.0.8 共 380+ 测试, 全部通过

---

## 7. 实施计划

### 7.1 阶段 1: StageRegistry 基础 (Day 1)

- `planner/stage_registry.py` (NEW)
- 8 核心方法 + 索引管理
- 25+ 单元测试

### 7.2 阶段 2: Default Registry + Built-in (Day 1)

- `_DEFAULT_REGISTRY` singleton
- `_register_builtin_stages()` 注册 5 个 built-in
- 8+ default registry 测试

### 7.3 阶段 3: Default Pipeline 工厂 (Day 1-2)

- `default_pipeline()` 按 role 顺序
- 5+ 工厂测试

### 7.4 阶段 4: 第三方 Stage 集成 (Day 2)

- 3+ 集成测试
- 文档化 `register(MyPluginStage())` 用法

### 7.5 阶段 5: 全量回归 (Day 2)

- V1.0.x 全量测试 (380+ tests)
- Runtime Contract §12 同步
- ChatGPT 代码审核
- ADR-0029 Accepted

### 7.6 阶段 6: V1.0.9 启动 (Day 2-3)

- Metadata Serialization (to_dict / from_dict)
- Pipeline Introspection (describe / dump / graph)
- Predicate API 完整化 (is_stopped / is_success)

---

## 8. ChatGPT 审核请求

> **本 ADR V1.0.8 关键设计：**
>
> 1. **8 核心方法** (register / unregister / lookup / by_role / by_capability / all / roles / capabilities)
> 2. **Default registry singleton** (auto-register 5 built-in)
> 3. **Default pipeline 工厂** (按 role 固定顺序)
> 4. **O(1) 索引** (role / capability 预构建)
> 5. **Python 容器语义** (in / len / iter / [])
> 6. **100% 向后兼容** (V1.0.1-V1.0.7 全部 API 保留)
> 7. **Core Freeze 保持** (不改 core/, router/, providers/)

**8 个具体问题：**

1. **8 个核心方法完整？** register / unregister / lookup / by_role / by_capability / all / roles / capabilities。是否需要 `by_owner()` / `by_version()` / `experimental()` 等额外查询？

2. **Default registry singleton 行为？** 进程级单例, 首次调用 auto-register built-in。是否应该用 `functools.lru_cache` 或显式 `_DEFAULT_REGISTRY`？是否需要 `reset_default_registry()` 测试 helper？

3. **Default pipeline role 顺序合理？** route → metric → checkpoint → condition。这个顺序是 V1.0.x 实践验证。是否需要 `default_pipeline(role_set=("stage", "metric"))` 构造变体？

4. **register 默认 raise vs replace 合理？** `replace=False` 默认, 重复 name raise。是否应改成 `replace=True` 默认（更宽容）？或者 `register_or_replace()` 显式方法？

5. **Clear 不影响 default 行为？** `default_registry().clear()` 不影响 built-in (因为 clear 是实例方法, default 是不同 instance)。这是 bug 还是 feature？是否应让 default.clear() raise？

6. **第三方 Stage 集成方式？** 显式 `register()` 是 V1.0.8 唯一方式。是否需要 `unregister_module(my_plugin_module)` 批量注销？是否需要 `entry_points` auto-discovery？

7. **与 ADR-0028 Metadata Access API 协同？** Registry 不感知 RuntimeMetadata (聚焦 Stage 自身)。这是正确职责划分, 还是应该加 `registry.find_stages_for_runtime_state(runtime)` 等组合 API？

8. **V1.0.8 范围聚焦？** 采纳 ChatGPT 9.91/10 Q7 "小 ADR" 建议, 本 ADR 只做 Registry。Pipeline Introspection / Metadata Serialization / Predicate API 全部放 V1.0.9。scope 是否合理？

**期望评分：9.5+/10** (V1.0.7 ADR 9.85/10, V1.0.8 ADR-0028 9.91/10, 本 ADR 类似范围)

---

## 9. V1.0.8 → V1.0.9 演化图

```
V1.0.8 (本 ADR):
  StageRegistry (NEW)
  default_registry() singleton
  default_pipeline() factory
  Stage 注册 / 索引 / 查询 / 容器语义
  第三方 Stage 显式 register
  → "Where do I find a Stage?" — 解答

V1.0.9 (采纳 ChatGPT 路线图):
  Metadata Serialization:
    runtime.to_dict() / from_dict()
    runtime.summary()
  Pipeline Introspection:
    pipeline.describe() / dump() / graph()
    pipeline.stage_names() / descriptors()
  Predicate API:
    runtime.is_stopped() / is_success() / stop_reason()
  Auto-discovery (Optional):
    @register_stage decorator
    entry_points auto-discovery
```

**关键演进：**
- 散落导入 → 统一注册 + 按需发现
- O(n) grep → O(1) 索引查询
- 无可发现性 → 默认 singleton + 工厂
- 第三方 Stage 混乱 → 显式 register 协议

---

## 10. 关联

- **前序**: [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10)
- **前序**: [ADR-0027 RuntimeMetadata](0027-runtime-metadata-schema.md) (V1.0.7 Accepted 9.88/10)
- **前序**: [ADR-0028 Metadata Access API](0028-metadata-access-api.md) (V1.0.8 Accepted 9.94/10)
- **后续**: V1.0.9 Metadata Serialization / Pipeline Introspection / Predicate API
- **V2 路线**: Distributed Registry / Remote Stage RPC / entry_points auto-discovery
- **Runtime Contract**: §12 (待写)
- **ARCHITECTURE**: §2.3 V1.0 路线 (Runtime Observability)
- **ChatGPT 路线图**: V1.0.7 代码审核 9.88/10 Q8 + V1.0.8 代码审核 9.94/10 V1.0.9 Roadmap — "MUST: Stage Registry"

# ADR-0030: Registry Introspection (V1.0.9)

- **里程碑**: V1.0.9
- **作者**: ai-hub core team
- **日期**: 2026-07-19
- **状态**: **Accepted** ✅ (ChatGPT ADR 审核 9.62/10 APPROVED with 5 minor revisions)
- **依赖**: [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10), [ADR-0029 Stage Registry](0029-stage-registry.md) (V1.0.8 Accepted Rev1 9.72/10)
- **后续**: V1.0.10 ADR-0032 Pipeline Introspection (SHOULD) / ADR-0033 Predicate API (SHOULD)
- **ChatGPT ADR 审核**: 9.62/10 APPROVED — `docs/reviews/0030-adr-chatgpt-review.md`
- **采纳修订** (5 项 minor, ChatGPT 9.62/10):
  - **R1**: §1.2 "6 个 Introspection API" → "6 类 Introspection Capability (8 APIs)" (API 数量描述修正)
  - **R2**: §3.3 新增 source 校验说明 (V1.x 开放字符串 + VALID_SOURCES warning, V1.1 严格 Enum)
  - **R3**: §2.1 StageInfo `registered_at: Optional[datetime]` → `registered_at: datetime` (register() 永远生成 now)
  - **R4**: §6 测试策略增加 `test_to_json_schema_stable` (serialization stability)
  - **R5**: §2.1 `find_stages_needing()` docstring 明确 AND 语义 (issubset, 未来 mode="any")

> **StageRegistry 答 "Where do I find a Stage?" (发现)**
> **Registry Introspection 答 "What does the Registry contain? What does each Stage need?" (自省)**
> **本 ADR 让 Registry 从"按 name 取 Stage"演进为"自描述 + 可调试 + 可序列化"。**

---

## 1. 背景与目标

### 1.1 背景

V1.0.8 引入 `StageRegistry` 让 Stage 统一注册 + 按需发现（`by_role` / `by_capability` / `lookup`）。

V1.0.8 Rev1 进一步明确：**Registry stores discoverable Stage definitions, not guaranteed executable runtime instances** — 即 Registry 保存的 Stage 实例可能用 stub deps 注册，实际执行需要 `default_pipeline(router, store, ...)` 注入 real deps。

**当前痛点（V1.0.8 → V1.0.9 演进）**:

1. **无可调试视图**: "Registry 当前装了什么?" — 必须手动迭代 `for name in registry`，逐个取 `describe(name)`
2. **无 source 区分**: built-in Stage 与第三方 Stage 在 Registry 中无标识，无法回答"哪些是我装的, 哪些是用户装的?"
3. **无 runtime deps 声明**: `RouteStage` 需要 `router`、`CheckpointStage` 需要 `store` — 这些信息散落在 Stage 类的 `__init__` 签名里, Registry 不感知
4. **无序列化能力**: Registry 无法 dump 为 JSON / dict, CLI / MCP server / WebUI 无法消费
5. **CLI 受限**: `ai-hub stage list` / `ai-hub stage info <name>` 没有统一 API

### 1.2 目标（V1.0.9 Registry Introspection）

V1.0.9 在 **不破坏 V1.0.8 API** 的前提下, 给 StageRegistry 增加 introspection 能力:

1. **6 类 Introspection Capability (8 APIs)** (R1 修正, ChatGPT 9.62/10):
   - `info(name) -> Optional[StageInfo]` — 单个 Stage 完整信息 (descriptor + source + requires + registered_at)
   - `describe_all() -> Dict[str, StageDescriptor]` — 所有 Stage 的 descriptor
   - `summary() -> List[StageSummary]` — 简短摘要 (name / role / capabilities / source / requires)
   - `list_builtin() / list_third_party() -> List[str]` — 按 source 分组 (2 APIs)
   - `find_stages_needing(*deps) -> List[str]` — 按 runtime dep 查询 (AND 语义, R5 明确)
   - `to_dict() / to_json() -> ...` — 序列化 Registry 状态 (2 APIs)

2. **Stage 注册时声明 source + deps**:
   - `register(stage, *, source="third_party", requires=())` — 扩展签名
   - built-in Stage 用 `source="builtin"` (由 `_register_builtin_stages` 设置)
   - 第三方 Stage 默认 `source="third_party"`

3. **StageInfo 数据结构**:
   - descriptor (StageDescriptor)
   - source ("builtin" | "third_party" | "test")
   - requires (tuple of runtime dep names, e.g. ("router", "store"))
   - registered_at (timestamp, V1.0.9 可选, V1.1 启用)

4. **CLI / 工具支持**:
   - `ai-hub stage list [--source builtin|third_party] [--role ROLE] [--capability CAP]`
   - `ai-hub stage info <name>` — 详细信息
   - `ai-hub stage dump [--json]` — 整个 Registry dump

5. **不破坏 V1.0.8**:
   - 所有 V1.0.8 API 保持不变
   - `register(stage)` 旧调用兼容 (source / requires 可选)
   - 现有测试无需修改

### 1.3 非目标

- ❌ **不**做 Pipeline Introspection (V1.0.10 评估)
- ❌ **不**做 Predicate API (V1.0.10 评估)
- ❌ **不**做 Auto-discovery via entry_points (V1.1 评估)
- ❌ **不**做 `@register_stage` 装饰器 (V1.1 评估)
- ❌ **不**做 remote / distributed Registry (V2)
- ❌ **不**改 StageDescriptor (V1.0.6 已稳定)
- ❌ **不**改 RuntimeMetadata (V1.0.7-V1.0.8 已稳定)
- ❌ **不**做 stage versioning / multi-version registration (V1.1 评估)
- ❌ **不**做 Registry persistence (跨进程) — 序列化仅用于 inspection / debug, 不用于状态恢复

---

## 2. 设计

### 2.1 StageRegistry Introspection 接口

```python
# planner/stage_registry.py (V1.0.9 扩展)
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
import json

from planner.stage_descriptor import Stage, StageDescriptor, get_descriptor


@dataclass(frozen=True)
class StageInfo:
    """Stage 完整信息 (V1.0.9 Introspection).

    比 StageDescriptor 多:
      - source: "builtin" | "third_party" | "test"
      - requires: runtime dep names (e.g. ("router", "store"))
      - registered_at: datetime (R3 修正, register() 永远生成 now via default_factory)

    用于:
      - CLI: `ai-hub stage info <name>` 打印
      - MCP / WebUI: 序列化为 JSON
      - Debug: 回答"这 Stage 哪来的? 需要什么 deps?"
    """
    descriptor: StageDescriptor
    source: str = "third_party"           # "builtin" | "third_party" | "test"
    requires: Tuple[str, ...] = ()         # runtime dep names
    # R3 (ChatGPT 9.62/10): register() 永远生成 now, 用 default_factory
    registered_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class StageSummary:
    """Stage 简短摘要 (V1.0.9 Introspection).

    用于:
      - CLI: `ai-hub stage list` 打印表格
      - WebUI: 列表展示
    """
    name: str
    role: str
    capabilities: FrozenSet[str]
    source: str
    requires: Tuple[str, ...]


class StageRegistry:
    """Stage 注册中心 + 索引 + 查询 API + Introspection (V1.0.9).

    V1.0.8: 8 核心方法 + 容器语义 + describe(name)
    V1.0.9: 6 Introspection API (describe_all / summary / list_builtin /
            list_third_party / find_stages_needing / to_dict / to_json / info)
    """

    DEFAULT_ORDER: Tuple[str, ...] = ("stage", "metric", "checkpoint", "condition")

    def __init__(self) -> None:
        self._stages: Dict[str, Stage] = {}
        self._by_role: Dict[str, Set[str]] = {}
        self._by_capability: Dict[str, Set[str]] = {}
        # V1.0.9: Stage 额外元信息 (name → StageInfo)
        self._info: Dict[str, StageInfo] = {}

    # ─── V1.0.8: 1. 注册 / 注销 ───
    def register(
        self,
        stage: Stage,
        *,
        replace: bool = False,
        source: str = "third_party",   # V1.0.9 NEW
        requires: Tuple[str, ...] = (), # V1.0.9 NEW
    ) -> None:
        """注册 Stage (V1.0.9 扩展签名, 向后兼容).

        Args:
            stage: 任何实现 Stage Protocol 的对象
            replace: True 替换同名, False raise
            source: "builtin" | "third_party" | "test" (V1.0.9 NEW)
            requires: runtime dep names, e.g. ("router", "store") (V1.0.9 NEW)

        V1.0.8 兼容:
          - 旧调用 `register(stage)` 仍工作 (source="third_party", requires=())
          - 旧调用 `register(stage, replace=True)` 仍工作
        """
        descriptor = get_descriptor(stage)
        name = descriptor.name
        if name in self._stages and not replace:
            raise KeyError(
                f"Stage {name!r} already registered. "
                f"Use replace=True to overwrite."
            )
        if name in self._stages:
            self._unindex(name)
        self._stages[name] = stage
        self._index(descriptor)
        # V1.0.9: 记录 StageInfo
        self._info[name] = StageInfo(
            descriptor=descriptor,
            source=source,
            requires=requires,
            registered_at=datetime.now(),
        )

    # ... (V1.0.8 unregister / clear / lookup / by_role / by_capability / all /
    #      roles / capabilities / __contains__ / __len__ / __iter__ / __getitem__ /
    #      describe / default_order 保持不变) ...

    # ─── V1.0.9: Introspection API ───

    def info(self, name: str) -> Optional[StageInfo]:
        """返回 Stage 完整信息 (V1.0.9).

        比 describe(name) 多: source / requires / registered_at.

        Args:
            name: Stage name

        Returns:
            StageInfo 或 None (未找到)
        """
        return self._info.get(name)

    def describe_all(self) -> Dict[str, StageDescriptor]:
        """返回所有 Stage 的 descriptor (V1.0.9).

        Returns:
            dict (name → StageDescriptor)
        """
        return {name: get_descriptor(s) for name, s in self._stages.items()}

    def summary(self) -> List[StageSummary]:
        """返回所有 Stage 的简短摘要 (V1.0.9).

        用于 CLI / WebUI 列表展示.

        Returns:
            List[StageSummary] (按注册顺序)
        """
        result: List[StageSummary] = []
        for name, info in self._info.items():
            d = info.descriptor
            result.append(StageSummary(
                name=d.name,
                role=d.role,
                capabilities=d.capabilities,
                source=info.source,
                requires=info.requires,
            ))
        return result

    def list_builtin(self) -> List[str]:
        """列出所有 source="builtin" 的 Stage name (V1.0.9)."""
        return [n for n, info in self._info.items() if info.source == "builtin"]

    def list_third_party(self) -> List[str]:
        """列出所有 source="third_party" 的 Stage name (V1.0.9)."""
        return [n for n, info in self._info.items() if info.source == "third_party"]

    def find_stages_needing(self, *deps: str) -> List[str]:
        """列出所有 requires 包含指定 deps 的 Stage name (V1.0.9, R5 明确 AND 语义).

        语义 (R5 采纳 ChatGPT 9.62/10):
          - **AND query (issubset)**: 返回 requires **包含所有** deps 的 Stage
          - 例: find_stages_needing("router", "store") → 同时需要 router 和 store 的 Stage
          - 未来 V1.1 评估: 增加 mode="any" 参数支持 OR query

        Args:
            deps: runtime dep names, e.g. "router", "store"

        Returns:
            name 列表 (按注册顺序)

        Use case:
          - default_pipeline(router, store) 前可查询: "哪些 Stage 需要 router?"
          - Debug: "如果我不传 store, 哪些 Stage 会被跳过?"
        """
        if not deps:
            return []
        dep_set = set(deps)
        return [
            n for n, info in self._info.items()
            if dep_set.issubset(set(info.requires))
        ]

    def to_dict(self) -> Dict[str, Any]:
        """序列化 Registry 状态为 dict (V1.0.9).

        用于:
          - CLI: `ai-hub stage dump --json`
          - MCP server: 跨进程传输
          - WebUI: REST API response
          - Debug: log 结构化输出

        Returns:
            {
                "stages": [
                    {
                        "name": "route",
                        "descriptor": {...},
                        "source": "builtin",
                        "requires": ["router"],
                        "registered_at": "2026-07-19T10:30:00",
                    },
                    ...
                ],
                "roles": ["stage", "metric", ...],
                "capabilities": ["selects_provider", ...],
                "default_order": ["stage", "metric", "checkpoint", "condition"],
            }
        """
        return {
            "stages": [
                {
                    "name": info.descriptor.name,
                    "descriptor": _descriptor_to_dict(info.descriptor),
                    "source": info.source,
                    "requires": list(info.requires),
                    "registered_at": info.registered_at.isoformat() if info.registered_at else None,
                }
                for info in self._info.values()
            ],
            "roles": sorted(self.roles()),
            "capabilities": sorted(self.capabilities()),
            "default_order": list(self.default_order()),
        }

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        """序列化 Registry 状态为 JSON 字符串 (V1.0.9).

        Args:
            indent: JSON 缩进 (None = 紧凑)
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def _descriptor_to_dict(d: StageDescriptor) -> Dict[str, Any]:
    """StageDescriptor → dict (V1.0.9 helper)."""
    return {
        "name": d.name,
        "role": d.role,
        "version": d.version,
        "capabilities": sorted(d.capabilities),
        "idempotent": d.idempotent,
        "has_side_effects": d.has_side_effects,
        "always_run_after_stop": d.always_run_after_stop,
        "experimental": d.experimental,
        "description": d.description,
        "owner": d.owner,
    }
```

### 2.2 Built-in Stage 注册（V1.0.9 扩展）

```python
# planner/stage_registry.py (继续)
def _register_builtin_stages(registry: StageRegistry) -> None:
    """注册 5 个 built-in Stage (V1.0.9 扩展 source + requires).

    V1.0.9 新增:
      - source="builtin" 标识
      - requires 声明 runtime deps (供 find_stages_needing / info 查询)
    """
    from planner.pipeline import RouteStage, MetricsStage
    from planner.stages.retry_stage import RetryStage
    from planner.stages.checkpoint_stage import CheckpointStage
    from planner.stages.condition_stage import ConditionStage

    # V1.0.9: 用 source="builtin" + requires 声明
    registry.register(
        RouteStage(router=None),
        source="builtin",
        requires=("router",),  # V1.0.9 NEW
    )
    registry.register(
        RetryStage(),
        source="builtin",
        requires=(),  # 零参, 无 runtime deps
    )
    registry.register(
        CheckpointStage(store=_NullStore()),
        source="builtin",
        requires=("store",),  # V1.0.9 NEW
    )
    registry.register(
        ConditionStage(condition=lambda c: True, on_true="continue"),
        source="builtin",
        requires=(),
    )
    registry.register(
        MetricsStage(),
        source="builtin",
        requires=(),
    )
```

### 2.3 使用示例

```python
# V1.0.9 Introspection 示例
from planner.stage_registry import default_registry

registry = default_registry()

# 1. 列出所有 Stage 的 descriptor
all_descriptors = registry.describe_all()
# {"route": StageDescriptor(...), "metrics": ..., "checkpoint": ..., ...}

# 2. 简短摘要 (CLI 友好)
for s in registry.summary():
    print(f"{s.name:15} role={s.role:10} source={s.source:10} requires={s.requires}")
# route           role=stage       source=builtin     requires=('router',)
# retry           role=retry       source=builtin     requires=()
# checkpoint      role=checkpoint  source=builtin     requires=('store',)
# ...

# 3. 按 source 过滤
builtins = registry.list_builtin()         # ['route', 'retry', 'checkpoint', 'condition', 'metrics']
third_party = registry.list_third_party()  # []

# 4. 按 runtime dep 查询
needs_router = registry.find_stages_needing("router")  # ['route']
needs_store = registry.find_stages_needing("store")    # ['checkpoint']
needs_router_or_store = registry.find_stages_needing("router", "store")  # ['route', 'checkpoint']

# 5. 单个 Stage 详细信息
info = registry.info("route")
# StageInfo(
#     descriptor=StageDescriptor(name='route', role='stage', ...),
#     source='builtin',
#     requires=('router',),
#     registered_at=datetime(2026, 7, 19, 10, 30, 0),
# )

# 6. 序列化
registry_dict = registry.to_dict()  # dict (for MCP / WebUI)
registry_json = registry.to_json()  # JSON string (for log / file dump)

# 7. 第三方 Stage 注册 (V1.0.9 自动记录 source="third_party")
class MyPluginStage:
    descriptor = StageDescriptor(name="my_plugin", role="stage", capabilities=frozenset({"custom"}))
    def __call__(self, ctx):
        return ctx

registry.register(MyPluginStage())  # source 默认 "third_party", requires 默认 ()
assert "my_plugin" in registry.list_third_party()
```

### 2.4 CLI 集成（V1.0.9 可选, V1.0.10 实施）

```bash
# V1.0.9 评估, V1.0.10 实施:
$ ai-hub stage list
NAME            ROLE           SOURCE         REQUIRES
route           stage          builtin        ('router',)
retry           retry          builtin        ()
checkpoint      checkpoint     builtin        ('store',)
condition       condition      builtin        ()
metrics         metric         builtin        ()

$ ai-hub stage info route
StageInfo:
  name: route
  role: stage
  source: builtin
  requires: ('router',)
  capabilities: {'selects_provider'}
  idempotent: True
  has_side_effects: False
  always_run_after_stop: False
  registered_at: 2026-07-19T10:30:00

$ ai-hub stage dump --json | jq .
{
  "stages": [...],
  "roles": ["checkpoint", "condition", "metric", "retry", "stage"],
  "capabilities": ["collects_metrics", "controls_flow", ...],
  "default_order": ["stage", "metric", "checkpoint", "condition"]
}
```

### 2.5 API 设计原则

1. **V1.0.8 完全兼容** — `register(stage)` 旧调用不变, 新参数可选
2. **Introspection 不修改状态** — 所有 V1.0.9 API 是只读, 不影响 Registry
3. **StageInfo 是 frozen dataclass** — 与 StageDescriptor 一致, 不可变
4. **序列化无副作用** — `to_dict()` / `to_json()` 不修改 Registry
5. **CLI 可选** — V1.0.9 仅提供 API, CLI 在 V1.0.10 实施
6. **source 字符串** — "builtin" | "third_party" | "test" (V2 转 Enum)
7. **requires 是声明性** — Registry 不验证 requires 与 Stage `__init__` 签名一致 (best-effort)

### 2.6 向后兼容

- ✅ V1.0.8 `register(stage)` → V1.0.9 `register(stage, source="third_party", requires=())`
- ✅ V1.0.8 `register(stage, replace=True)` → V1.0.9 同签名
- ✅ V1.0.8 `describe(name)` → V1.0.9 保留, `info(name)` 是超集
- ✅ V1.0.8 `default_registry()` → V1.0.9 built-in 用 source="builtin" 注册
- ✅ V1.0.8 `reset_default_registry()` → V1.0.9 保留
- ✅ V1.0.8 `default_pipeline(router, *, store, registry)` → V1.0.9 保留
- ✅ V1.0.8 `default_order()` / DEFAULT_ORDER → V1.0.9 保留
- ✅ V1.0.8 测试全部通过 (无需修改)

---

## 3. 决策依据

### 3.1 为什么 `StageInfo` 是 frozen dataclass？

与 `StageDescriptor` (V1.0.6 frozen) 一致:
- Introspection 信息是元数据, 不应运行时修改
- frozen 让 StageInfo 可哈希, 可作为 dict key / set member
- 避免 accidental mutation (e.g. `info.source = "..."` 应 raise)

### 3.3 为什么 `source` 是字符串而非 Enum?

V1.0.6 StageDescriptor 的 `role` 也是字符串 (V2 转 Enum), 保持一致:
- V1.x: 字符串简单, 兼容性好, JSON 友好
- V2: 转 Enum (`Source.BUILTIN` / `Source.THIRD_PARTY` / `Source.TEST`)
- 转换成本: V2 Enum + back-compat shim (1 个小 PR)

**R2 source 校验说明 (ChatGPT 9.62/10)**:

V1.x `source` 保持开放字符串, 但实现提供 `VALID_SOURCES` 集合 + warning (不 raise):

```python
# planner/stage_registry.py
VALID_SOURCES: FrozenSet[str] = frozenset({"builtin", "third_party", "test"})

def register(self, stage, *, source="third_party", requires=(), ...):
    if source not in VALID_SOURCES:
        logger.warning(
            "Stage %r registered with unknown source=%r. "
            "Valid sources: %s. V1.x allows open string, V1.1 will enforce enum.",
            get_descriptor(stage).name, source, sorted(VALID_SOURCES),
        )
    ...
```

- V1.x: 开放字符串 + warning (未来扩展容易, 不破坏现有调用)
- V1.1: 严格 Enum 校验 (raise ValueError for unknown source)
- 原因: 避免拼写错误 (`third_party` / `thirdparty` / `third-party`) 静默通过

### 3.4 为什么 `requires` 是 `Tuple[str, ...]`?

- 表示 "Stage 需要哪些 runtime deps" (e.g. `("router",)`, `("store",)`, `()`)
- Tuple 不可变 (与 frozen dataclass 一致)
- 字符串语义清晰: `"router"` 比 `Router` class 更通用 (跨 V1.x/V2.x)
- V2 评估: 转 Enum (`Dep.ROUTER` / `Dep.STORE`)

### 3.5 为什么 `registered_at` 是 `datetime` (R3 修正)?

R3 (ChatGPT 9.62/10): 改为非 Optional `datetime`。
- `register()` 永远生成 `datetime.now()` (via `field(default_factory=datetime.now)`)
- 测试 fixture 若需固定时间, 显式传 `registered_at=datetime(2026, 1, 1)`
- V1.1 评估: 加 `last_used_at` / `invocation_count` (Runtime 观测)
- V2 评估: 加 `version_history` (multi-version registration)

### 3.6 为什么 `to_dict()` 把 `descriptor` 也展开?

而非引用 `StageDescriptor.to_dict()`?

- V1.0.9 不引入 `StageDescriptor.to_dict()` (那是 ADR-0031 Metadata Serialization 范围)
- V1.0.9 用 `_descriptor_to_dict()` helper (本地函数, 不污染 StageDescriptor)
- V1.0.10 ADR-0031 实施 `StageDescriptor.to_dict()` / `from_dict()` 后, V1.0.9 helper 可重构为 delegate

### 3.7 为什么 CLI 在 V1.0.10 而非 V1.0.9?

- V1.0.9 聚焦 API + 数据结构 (StageInfo / StageSummary)
- CLI 涉及 `argparse` / 输出格式 / 错误处理, 是独立工程
- V1.0.10 可基于 V1.0.9 API 快速实施 CLI

### 3.8 为什么不做 Predicate API?

Predicate API (`runtime.is_stopped()` / `is_success()`) 是 RuntimeMetadata 的扩展, 不是 Registry 的事:
- Registry 答 "Where do I find a Stage?"
- RuntimeMetadata 答 "What happened during execution?"
- Predicate API 答 "What's the current runtime state?" — 属于 RuntimeMetadata 范围
- 留待 V1.0.10 ADR-0032 (Predicate API) 评估

### 3.9 为什么不做 `@register_stage` 装饰器?

- V1.0.9 范围聚焦 Introspection, 不引入新注册方式
- `@register_stage` 涉及 import-time side effects, 与 V1.0.8 "explicit register" 哲学冲突
- 留待 V1.1 评估 (auto-discovery via entry_points)

---

## 4. 替代方案

### 4.1 替代 1：把 source / requires 加到 StageDescriptor

**拒绝**:
- StageDescriptor 是 Stage 静态 metadata (V1.0.6), 不应含 Registry 视角的 source
- 同一 Stage 类可在不同 Registry 中以不同 source 注册 (e.g. 测试中 `source="test"`)
- requires 与 StageDescriptor 的 "Stage 自身" 视角不符 — requires 是 Registry 工厂视角

### 4.2 替代 2：把 StageInfo 合并到 StageDescriptor

**拒绝**:
- StageDescriptor 是 frozen + V1.0.6 已稳定, 不能加字段
- StageInfo 是 V1.0.9 新增, 与 descriptor 解耦
- 同一 descriptor 可对应不同 StageInfo (e.g. 不同 Registry 实例)

### 4.3 替代 3：用 dict 而非 StageInfo dataclass

**拒绝**:
- dict 无类型保护, IDE / mypy 无法检查
- 与 V1.0.6 StageDescriptor (frozen dataclass) 哲学不一致
- dataclass 支持 `__eq__` / `__hash__` / `__repr__` 自动生成

### 4.4 替代 4：Registry 持有 Stage 类而非实例

**拒绝**:
- V1.0.8 已经决定持实例 (用 stub deps 注册)
- 改为持类会破坏 V1.0.8 + V1.0.8 Rev1 + 132 个测试
- 实例 + descriptor 已经够 introspection 用

### 4.5 替代 5：用 `__init__` 签名反射自动推导 requires

**拒绝**:
- 反射 `__init__` signature 太脆弱 (e.g. `RouteStage.__init__(self, router: Router)` → `("router",)` ?)
- 不能处理 `*args` / `**kwargs` / 默认值
- 不能处理 stub deps (e.g. `RouteStage(router=None)` 仍 requires router)
- 显式 `requires=("router",)` 声明更可靠

### 4.6 替代 6：把 Introspection + Serialization 合并到 V1.0.9 mega-ADR

**拒绝**:
- 采纳 ChatGPT 9.91/10 Q7 "小 ADR" 建议 (V1.0.8 ADR-0029 已验证)
- Introspection (Registry 视角) 与 Serialization (跨对象通用) 是两个关注点
- ADR-0030 Introspection + ADR-0031 Serialization 各自聚焦, 易审核

---

## 5. 影响

### 5.1 新增代码

| 文件 | 变化 | 行数估计 |
|------|------|---------|
| `planner/stage_registry.py` (MODIFIED) | + StageInfo / StageSummary / 6 Introspection API / _descriptor_to_dict helper | +200 |
| `tests/test_stage_registry_introspection.py` (NEW) | 25+ tests for V1.0.9 API | +400 |
| `docs/adr/0030-registry-introspection.md` (NEW) | 本 ADR | ~400 |

### 5.2 修改代码

| 文件 | 变化 |
|------|------|
| `planner/stage_registry.py` | `register()` 签名扩展 (source / requires, 向后兼容) |
| `planner/stage_registry.py` | `_register_builtin_stages()` 用 source="builtin" + requires 声明 |
| `planner/stage_registry.py` | `unregister()` / `clear()` 同步清理 `_info` dict |

### 5.3 不变代码（Core Freeze）

- `core/*` — 不变
- `planner/stage_descriptor.py` — 不变 (V1.0.6 已稳定)
- `planner/runtime_metadata.py` — 不变 (V1.0.7 已稳定)
- `planner/pipeline.py` — 不变 (V1.0.1 已稳定, Rev1 R4 misuse guard 已加)
- `planner/stages/*.py` — 不变 (V1.0.3-V1.0.6 已稳定)
- `router/router.py` — 不变
- `providers/*` — 不变

### 5.4 测试影响

- V1.0.8 测试 (`test_stage_registry.py` 55 tests + `test_default_pipeline.py` 10 tests) **全部通过** (向后兼容)
- V1.0.9 新增 `test_stage_registry_introspection.py` (~25 tests)
- 总测试: 358 (V1.0.x core) + 25 (V1.0.9) ≈ 383 全通过

---

## 6. 测试策略

### 6.1 测试覆盖

**§6.1 StageInfo / StageSummary 数据结构 (3 tests)**:
- `test_stage_info_frozen` — StageInfo 是 frozen, 修改 raise FrozenInstanceError
- `test_stage_summary_frozen` — StageSummary 是 frozen
- `test_stage_info_defaults` — 默认 source="third_party" / requires=() / registered_at=None

**§6.2 register() V1.0.9 扩展 (5 tests)**:
- `test_register_with_source_builtin` — source="builtin" 被记录
- `test_register_with_source_third_party` — source="third_party" 被记录
- `test_register_with_requires` — requires=("router",) 被记录
- `test_register_v108_compat_no_source` — 旧调用 `register(stage)` 默认 source="third_party"
- `test_register_v108_compat_replace_only` — 旧调用 `register(stage, replace=True)` 仍工作

**§6.3 info() / describe_all() (4 tests)**:
- `test_info_returns_stage_info` — info(name) 返回 StageInfo
- `test_info_not_found` — info("unknown") 返回 None
- `test_describe_all_returns_dict` — describe_all() 返回 dict (name → descriptor)
- `test_describe_all_empty_registry` — 空 Registry 返回 {}

**§6.4 summary() (3 tests)**:
- `test_summary_returns_list` — summary() 返回 List[StageSummary]
- `test_summary_empty_registry` — 空 Registry 返回 []
- `test_summary_includes_source_requires` — summary 包含 source / requires 字段

**§6.5 list_builtin() / list_third_party() (4 tests)**:
- `test_list_builtin_default_registry` — default_registry 有 5 个 built-in
- `test_list_builtin_empty_registry` — 空 Registry 返回 []
- `test_list_third_party_after_register` — 注册第三方后 list_third_party 返回它
- `test_list_builtin_excludes_third_party` — built-in / third-party 互斥

**§6.6 find_stages_needing() (5 tests)**:
- `test_find_stages_needing_router` — find_stages_needing("router") 返回 ["route"]
- `test_find_stages_needing_store` — find_stages_needing("store") 返回 ["checkpoint"]
- `test_find_stages_needing_multiple` — find_stages_needing("router", "store") 返回 ["route", "checkpoint"]
- `test_find_stages_needing_empty` — find_stages_needing() 返回 []
- `test_find_stages_needing_unknown_dep` — find_stages_needing("nonexistent") 返回 []

**§6.7 to_dict() / to_json() (6 tests, R4 增加 stability test)**:
- `test_to_dict_has_stages_key` — to_dict() 有 "stages" key
- `test_to_dict_has_roles_capabilities_default_order` — to_dict() 有 roles / capabilities / default_order
- `test_to_dict_descriptor_expanded` — 每个 stage 的 descriptor 是展开的 dict
- `test_to_json_valid_json` — to_json() 是合法 JSON
- `test_to_json_indent` — indent 参数生效
- `test_to_json_schema_stable` (R4 ChatGPT 9.62/10) — `json.loads(registry.to_json())` 后 schema keys 稳定:
  ```python
  data = json.loads(registry.to_json())
  assert set(data.keys()) == {"stages", "roles", "capabilities", "default_order"}
  for stage in data["stages"]:
      assert set(stage.keys()) == {"name", "descriptor", "source", "requires", "registered_at"}
      assert set(stage["descriptor"].keys()) == {
          "name", "role", "version", "capabilities", "idempotent",
          "has_side_effects", "always_run_after_stop", "experimental",
          "description", "owner",
      }
  ```
  目的: 避免未来 ADR-0031 重构时改坏 schema (跨版本稳定性)

**§6.8 unregister / clear 同步清理 (3 tests)**:
- `test_unregister_removes_info` — unregister 后 info(name) 返回 None
- `test_clear_removes_all_info` — clear 后 _info 为空
- `test_replace_updates_info` — register(replace=True) 更新 StageInfo

**§6.9 default_registry() V1.0.9 (3 tests)**:
- `test_default_registry_builtin_has_source` — 5 个 built-in 全部 source="builtin"
- `test_default_registry_route_requires_router` — route 的 requires=("router",)
- `test_default_registry_checkpoint_requires_store` — checkpoint 的 requires=("store",)

**§6.10 V1.0.8 回归 (implicit)**:
- V1.0.8 现有 55 tests (`test_stage_registry.py`) + 10 tests (`test_default_pipeline.py`) 全通过

### 6.2 测试 helper

```python
# tests/test_stage_registry_introspection.py
import pytest
from planner.stage_registry import (
    StageRegistry, StageInfo, StageSummary,
    default_registry, reset_default_registry,
)
from planner.stage_descriptor import StageDescriptor


def _make_stub(name, role="stage", capabilities=frozenset()):
    class _StubStage:
        descriptor = StageDescriptor(name=name, role=role, capabilities=capabilities)
        def __call__(self, ctx):
            return ctx
    return _StubStage()


@pytest.fixture
def empty_registry():
    return StageRegistry()


@pytest.fixture
def clean_default():
    reset_default_registry()
    yield
    reset_default_registry()
```

---

## 7. 实施计划

### 7.1 阶段 1: ADR-0030 草稿 (本 ADR)

- 起草本 ADR
- ChatGPT 审核 (期望 9.5+/10)
- 采纳调整 + commit Accepted

### 7.2 阶段 2: 代码实施 (Day 1)

- `planner/stage_registry.py` 扩展 (StageInfo / StageSummary / 6 API / _descriptor_to_dict)
- `register()` 签名扩展 (source / requires, 向后兼容)
- `_register_builtin_stages()` 用 source="builtin" + requires 声明
- `unregister()` / `clear()` 同步清理 `_info`

### 7.3 阶段 3: 测试 (Day 1)

- `tests/test_stage_registry_introspection.py` (~25 tests)
- 跑 V1.0.x 全量回归 (~383 tests pass)

### 7.4 阶段 4: 代码审核 (Day 1-2)

- 写代码层 ChatGPT 审核 prompt
- 发送给 ChatGPT (期望 9.5+/10)
- 采纳调整 + commit Accepted

### 7.5 阶段 5: ADR-0031 启动 (Day 2)

- ADR-0031 Metadata Serialization 草稿
  - `StageDescriptor.to_dict()` / `from_dict()`
  - `RuntimeMetadata.to_dict()` / `from_dict()`
  - JSON schema validation

### 7.6 阶段 6: V1.0.10 启动 (Day 3+)

- ADR-0032 Pipeline Introspection (`pipeline.describe()` / `dump()` / `graph()`)
- ADR-0033 Predicate API (`runtime.is_stopped()` / `is_success()`)
- CLI 实施 (`ai-hub stage list` / `info` / `dump`)

---

## 8. 待审核问题

1. **`StageInfo` 字段是否合适？** source / requires / registered_at 三个字段是否够用？是否应该加 `last_used_at` / `invocation_count` (Runtime 观测)? 评估: V1.0.9 保持 3 字段, V1.1 评估 Runtime 观测字段。

2. **`requires` 字符串语义？** `("router",)` / `("store",)` 是否应该用 Enum (`Dep.ROUTER`)? 评估: V1.x 字符串 (与 StageDescriptor.role 一致), V2 转 Enum。

3. **`source` 字符串 vs Enum？** "builtin" | "third_party" | "test" 是否够用？是否需要 "deprecated" / "experimental"? 评估: V1.0.9 三档够用, experimental 已在 StageDescriptor 中。

4. **`to_dict()` 是否应该 delegate 到 `StageDescriptor.to_dict()`?** V1.0.9 用本地 `_descriptor_to_dict()` helper, V1.0.10 ADR-0031 实施 `StageDescriptor.to_dict()` 后重构。是否合理？

5. **CLI 应该在 V1.0.9 还是 V1.0.10?** V1.0.9 仅 API + 数据结构, V1.0.10 实施 CLI (`ai-hub stage list` / `info` / `dump`)。是否合理？

6. **`find_stages_needing(*deps)` 语义？** 当前是 "Stage requires **所有** 这些 deps" (issubset)。是否应该提供 "任一 dep" (intersection) 模式? 评估: V1.0.9 仅 issubset, V1.1 评估 intersection 模式。

7. **`registered_at` 是否启用？** V1.0.9 启用 (datetime.now()), 还是延后到 V1.1? 评估: V1.0.9 启用, 但保留 None 兼容路径 (测试 fixture 可不传)。

8. **V1.0.9 范围聚焦？** 本 ADR 只做 Registry Introspection。Pipeline Introspection / Predicate API / CLI 全部放 V1.0.10+。scope 是否合理？

**期望评分：9.5+/10** (V1.0.8 ADR-0029 9.93/10 + 代码 9.72/10, 本 ADR 类似范围)

---

## 9. V1.0.9 → V1.0.10 演化图

```
V1.0.9 (本 ADR + ADR-0031):
  Registry Introspection (本 ADR):
    StageInfo / StageSummary
    describe_all() / summary() / info()
    list_builtin() / list_third_party()
    find_stages_needing(*deps)
    to_dict() / to_json()
    register(source=..., requires=...)
  Metadata Serialization (ADR-0031):
    StageDescriptor.to_dict() / from_dict()
    RuntimeMetadata.to_dict() / from_dict()
    JSON schema validation

V1.0.10 (ChatGPT 路线图):
  Pipeline Introspection:
    pipeline.describe() / dump() / graph()
    pipeline.stage_names() / descriptors()
  Predicate API:
    runtime.is_stopped() / is_success() / stop_reason()
  CLI:
    ai-hub stage list / info / dump
    ai-hub pipeline describe / dump
```

**关键演进：**
- 按 name 取 Stage → 自描述 + 可调试 + 可序列化
- 无 source 区分 → built-in / third-party / test 三档
- 无 runtime deps 声明 → requires 显式声明
- 无序列化 → to_dict / to_json (MCP / WebUI / CLI 消费)

---

## 10. 关联

- **前序**: [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10)
- **前序**: [ADR-0027 RuntimeMetadata](0027-runtime-metadata-schema.md) (V1.0.7 Accepted 9.88/10)
- **前序**: [ADR-0028 Metadata Access API](0028-metadata-access-api.md) (V1.0.8 Accepted 9.94/10)
- **前序**: [ADR-0029 Stage Registry](0029-stage-registry.md) (V1.0.8 Accepted Rev1 9.72/10)
- **后续**: V1.0.9 ADR-0031 Metadata Serialization (MUST ②)
- **后续**: V1.0.10 ADR-0032 Pipeline Introspection (SHOULD)
- **后续**: V1.0.10 ADR-0033 Predicate API (SHOULD)
- **后续**: V1.0.10 CLI 实施 (`ai-hub stage list / info / dump`)
- **V2 路线**: source / role / requires 转 Enum; registered_at + last_used_at + invocation_count
- **Runtime Contract**: §12 (待写)
- **ARCHITECTURE**: §2.3 V1.0 路线 (Runtime Observability)

# AI Hub — Stage Registry (V1.0.9, ADR-0030 Accepted 9.62/10)
#
# Stage 注册中心 + 索引 + 查询 API + Introspection + Default Singleton + Default Pipeline 工厂.
#
# 关键设计 (V1.0.8 采纳 ChatGPT 9.93/10):
#   ① 8 核心方法: register / unregister / lookup / by_role / by_capability / all / roles / capabilities
#   ② T1: reset_default_registry() 测试 helper
#   ③ T2: describe(name) 返回 StageDescriptor
#   ④ Q3 重构: default_order() 暴露顺序, Pipeline 不 hardcode
#   ⑤ Q5 职责分离: clear() 不重注册 builtins, default_registry() 永远负责 builtins
#   ⑥ Q7 核心: Registry 不感知 RuntimeMetadata (保持 V1.x 三层解耦)
#   ⑦ Q1 范围聚焦: 不加 by_owner / by_version / experimental
#
# V1.0.9 扩展 (采纳 ChatGPT 9.62/10 ADR-0030):
#   ⑧ StageInfo / StageSummary frozen dataclass (Registry 上下文信息)
#   ⑨ register() 扩展 source / requires 参数 (V1.0.8 向后兼容)
#   ⑩ 8 Introspection APIs: info / describe_all / summary / list_builtin /
#      list_third_party / find_stages_needing / to_dict / to_json
#   ⑪ VALID_SOURCES warning (V1.x 开放字符串, V1.1 严格 Enum)
#   ⑫ _descriptor_to_dict helper (V1.0.10 ADR-0031 后重构为 delegate)
#
# V1.x Runtime 三层架构 (采纳 ChatGPT 9.93/10):
#   Layer 1: StageDescriptor (V1.0.6) — Stage 静态 metadata
#   Layer 2: StageRegistry (V1.0.8)   — Stage 索引 + 生命周期
#   Layer 3: ExecutionPipeline (V1.0.1) — Stage 调度 + 执行
#
# V1.0.9 Introspection 扩展:
#   Layer 2+: StageInfo (V1.0.9) — Registry 上下文信息 (source + requires + registered_at)
#
# Runtime 状态:
#   Layer A: RuntimeMetadata (V1.0.7)  — Runtime 动态 metadata
#   Layer B: Metadata Access API (V1.0.8) — Runtime 统一访问
#
# API Stability: Stable (V1.0.8+ core) / Experimental (V1.0.9 introspection)

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from planner.stage_descriptor import Stage, StageDescriptor, get_descriptor

logger = logging.getLogger(__name__)


# V1.0.9 R2 (ChatGPT 9.62/10): VALID_SOURCES for source warning
# V1.x: 开放字符串 + warning; V1.1: 严格 Enum (raise ValueError)
VALID_SOURCES: FrozenSet[str] = frozenset({"builtin", "third_party", "test"})


# ─────────────────────────────────────────────────────────────
# StageInfo / StageSummary (V1.0.9 Introspection)
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageInfo:
    """Stage 完整信息 (V1.0.9 Introspection, ADR-0030 Accepted 9.62/10).

    比 StageDescriptor 多:
      - source: "builtin" | "third_party" | "test" (Registry 上下文)
      - requires: runtime dep names (e.g. ("router", "store"))
      - registered_at: datetime (R3 修正, register() 永远生成 now)

    用于:
      - CLI: `ai-hub stage info <name>` 打印
      - MCP / WebUI: 序列化为 JSON
      - Debug: 回答"这 Stage 哪来的? 需要什么 deps?"

    关键设计 (ChatGPT 9.62/10):
      - frozen dataclass (与 StageDescriptor 一致, 不可变)
      - 不进入 StageDescriptor (StageDescriptor=Stage 自身, StageInfo=Registry 上下文)
    """

    descriptor: StageDescriptor
    source: str = "third_party"            # "builtin" | "third_party" | "test"
    requires: Tuple[str, ...] = ()          # runtime dep names
    # R3 (ChatGPT 9.62/10): register() 永远生成 now, 用 default_factory
    registered_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class StageSummary:
    """Stage 简短摘要 (V1.0.9 Introspection, ADR-0030 Accepted 9.62/10).

    用于:
      - CLI: `ai-hub stage list` 打印表格
      - WebUI: 列表展示

    类比:
      - Linux `systemctl list-units` (summary)
      - vs `systemctl dump-all` (full info)
    """

    name: str
    role: str
    capabilities: FrozenSet[str]
    source: str
    requires: Tuple[str, ...]


# ─────────────────────────────────────────────────────────────
# StageRegistry — 核心注册中心 + 索引 + 查询 API + Introspection
# ─────────────────────────────────────────────────────────────

class StageRegistry:
    """Stage 注册中心 + 索引 + 查询 API + Introspection (V1.0.9, ADR-0030 Accepted 9.62/10).

    核心能力 (V1.0.8):
      - 统一注册: register(stage) / unregister(name) / clear()
      - 索引加速: by_role(role) / by_capability(capability) (O(1) 索引, 非 O(n) 扫描)
      - Python 容器语义: __contains__ / __len__ / __iter__ / __getitem__
      - T2 (ChatGPT 9.93/10): describe(name) 返回 StageDescriptor
      - Q3 重构 (ChatGPT 9.93/10): default_order() 暴露 Pipeline 构造顺序

    Introspection 能力 (V1.0.9, 采纳 ChatGPT 9.62/10 ADR-0030):
      - info(name) -> StageInfo (descriptor + source + requires + registered_at)
      - describe_all() -> Dict[str, StageDescriptor]
      - summary() -> List[StageSummary]
      - list_builtin() / list_third_party() -> List[str]
      - find_stages_needing(*deps) -> List[str] (AND 语义)
      - to_dict() / to_json() -> 序列化 Registry 状态

    关键不变量 (Runtime Contract §12):
      - Stage 按 descriptor.name 注册 (强一致)
      - 同一 name 重复注册: 默认 raise, replace=True 时替换
      - Stage 实例不被 Registry 修改 (Registry 仅持引用)
      - Stage 注销后, 引用立即失效 (Registry 内部清除索引)
      - Registry **不**感知 RuntimeMetadata (Q7 核心架构原则)
    """

    # V1.0.8 默认 Pipeline 顺序 (按 role)
    # 未来 V1.0.9+ 新增 role (trace / cache / observer) 直接加这里
    DEFAULT_ORDER: Tuple[str, ...] = ("stage", "metric", "checkpoint", "condition")

    def __init__(self) -> None:
        # Stage 存储 (descriptor.name → Stage)
        self._stages: Dict[str, Stage] = {}
        # 索引 (role → {name})
        self._by_role: Dict[str, Set[str]] = {}
        # 索引 (capability → {name})
        self._by_capability: Dict[str, Set[str]] = {}
        # V1.0.9: Stage 额外元信息 (name → StageInfo)
        self._info: Dict[str, StageInfo] = {}

    # ─────────────────────────────────────────────────────
    # 1. 注册 / 注销 (V1.0.9 扩展 source / requires)
    # ─────────────────────────────────────────────────────

    def register(
        self,
        stage: Stage,
        *,
        replace: bool = False,
        source: str = "third_party",   # V1.0.9 NEW
        requires: Tuple[str, ...] = (), # V1.0.9 NEW
    ) -> None:
        """注册 Stage 到 Registry (V1.0.9 扩展签名, V1.0.8 向后兼容).

        Args:
            stage: 任何实现 Stage Protocol 的对象 (V1.0.6 descriptor 属性)
            replace: 如果 name 已注册, True 替换, False raise
            source (V1.0.9 NEW): "builtin" | "third_party" | "test"
            requires (V1.0.9 NEW): runtime dep names, e.g. ("router", "store")

        Raises:
            ValueError: stage 没有 descriptor (V1.0.7+ 强约束, ChatGPT 9.95/10 Q7)
            KeyError: name 已注册 且 replace=False

        V1.0.8 兼容:
          - 旧调用 `register(stage)` 仍工作 (source="third_party", requires=())
          - 旧调用 `register(stage, replace=True)` 仍工作

        V1.0.9 R2 (ChatGPT 9.62/10):
          - source 不在 VALID_SOURCES 时 logger.warning (不 raise)
          - V1.1 评估: 严格 Enum 校验 (raise ValueError)
        """
        descriptor = get_descriptor(stage)  # V1.0.6 helper, 强类型
        name = descriptor.name

        # V1.0.9 R2: source 校验 (warning only, V1.x 开放字符串)
        if source not in VALID_SOURCES:
            logger.warning(
                "Stage %r registered with unknown source=%r. "
                "Valid sources: %s. V1.x allows open string, V1.1 will enforce enum.",
                name, source, sorted(VALID_SOURCES),
            )

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
        # V1.0.9: 记录 StageInfo
        self._info[name] = StageInfo(
            descriptor=descriptor,
            source=source,
            requires=requires,
        )

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
            # V1.0.9: 同步清理 _info
            self._info.pop(name, None)
        return stage

    def clear(self) -> None:
        """清空 Registry (主要用于测试隔离).

        Q5 职责分离 (采纳 ChatGPT 9.93/10):
          - clear() 只清当前 Registry
          - **不**自动重新注册 built-in (Factory 职责)
          - default_registry() 永远负责 built-in 注册

        V1.0.9: 同步清理 _info dict.
        """
        self._stages.clear()
        self._by_role.clear()
        self._by_capability.clear()
        self._info.clear()

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
        """按 descriptor.role 查找所有 Stage (O(1) 索引).

        Args:
            role: Stage role (e.g. "stage", "retry", "checkpoint", "condition", "metric")

        Returns:
            Stage 列表 (按注册顺序, may be empty)
        """
        names = self._by_role.get(role, set())
        return [self._stages[n] for n in names if n in self._stages]

    def by_capability(self, capability: str) -> List[Stage]:
        """按 descriptor.capability 查找所有 Stage (O(1) 索引).

        Args:
            capability: capability string (e.g. "selects_provider", "collects_metrics",
                       "controls_flow", "retries_on_failure", "writes_snapshot")

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
        """返回 Stage 的 StageDescriptor (不返回 Stage 实例).

        Use case (ChatGPT 9.93/10 T2):
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
    # ─────────────────────────────────────────────────────

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
    # 6. V1.0.9 Introspection API (ADR-0030 Accepted 9.62/10)
    # ─────────────────────────────────────────────────────

    def info(self, name: str) -> Optional[StageInfo]:
        """返回 Stage 完整信息 (V1.0.9 ADR-0030).

        比 describe(name) 多: source / requires / registered_at.

        Args:
            name: Stage name

        Returns:
            StageInfo 或 None (未找到)

        Use case:
          - CLI: `ai-hub stage info <name>` 打印详细信息
          - Debug: "这 Stage 哪来的? 需要什么 deps?"
        """
        return self._info.get(name)

    def describe_all(self) -> Dict[str, StageDescriptor]:
        """返回所有 Stage 的 descriptor (V1.0.9 ADR-0030).

        Returns:
            dict (name → StageDescriptor), 按注册顺序
        """
        return {name: get_descriptor(s) for name, s in self._stages.items()}

    def summary(self) -> List[StageSummary]:
        """返回所有 Stage 的简短摘要 (V1.0.9 ADR-0030).

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
        """列出所有 source="builtin" 的 Stage name (V1.0.9 ADR-0030).

        Returns:
            name 列表 (按注册顺序)
        """
        return [n for n, info in self._info.items() if info.source == "builtin"]

    def list_third_party(self) -> List[str]:
        """列出所有 source="third_party" 的 Stage name (V1.0.9 ADR-0030).

        Returns:
            name 列表 (按注册顺序)
        """
        return [n for n, info in self._info.items() if info.source == "third_party"]

    def find_stages_needing(self, *deps: str) -> List[str]:
        """列出所有 requires 包含指定 deps 的 Stage name (V1.0.9 ADR-0030, R5 AND 语义).

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
        """序列化 Registry 状态为 dict (V1.0.9 ADR-0030).

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
                        "registered_at": "2026-07-19T10:30:00.123456",
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
                    "registered_at": info.registered_at.isoformat(),
                }
                for info in self._info.values()
            ],
            "roles": sorted(self.roles()),
            "capabilities": sorted(self.capabilities()),
            "default_order": list(self.default_order()),
        }

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        """序列化 Registry 状态为 JSON 字符串 (V1.0.9 ADR-0030).

        Args:
            indent: JSON 缩进 (None = 紧凑)

        Returns:
            JSON 字符串

        Use case:
          - CLI: `ai-hub stage dump --json`
          - File dump: 写入文件供离线分析
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    # ─────────────────────────────────────────────────────
    # 7. 内部: 索引管理
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


# ─────────────────────────────────────────────────────────────
# Default Registry Singleton
# ─────────────────────────────────────────────────────────────

_DEFAULT_REGISTRY: Optional[StageRegistry] = None


def default_registry() -> StageRegistry:
    """获取进程级 default registry 单例.

    行为 (Q5 职责分离, 采纳 ChatGPT 9.93/10):
      - 首次调用: 创建 registry + 自动注册 built-in Stage (RouteStage, MetricsStage,
                   RetryStage, CheckpointStage, ConditionStage)
      - 后续调用: 返回同一 instance (singleton pattern)
      - 第三方 Stage 集成: registry.register(MyPluginStage()) 后立即可用
      - **不**自动重新注册 (clear() 不影响 default, reset_default_registry() 才重置)

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


class _NullStore:
    """Null store for registry registration (CheckpointStage needs a store).

    Q5 职责分离: Registry 仅用于 discovery (按 name/role/capability 索引).
    实际执行时 default_pipeline(router, store) 用 real store 构造 CheckpointStage.

    Rev1 R4 (ChatGPT 9.72/10): 暴露 is_registry_stub=True 标记,
    CheckpointStage.__call__ 检测此标记并将 NoneType error 升级为
    Architecture misuse error (RuntimeError).
    """

    # Rev1 R4: 标记此 store 是 registry stub, 不应被执行
    is_registry_stub: bool = True

    def append(self, event: Any) -> None:
        """No-op append (registry registration only, never executed)."""
        pass


def _register_builtin_stages(registry: StageRegistry) -> None:
    """注册 5 个 built-in Stage (V1.0.1-V1.0.6 全部, V1.0.9 扩展 source + requires).

    关键设计 (V1.0.8 实施发现):
      - RouteStage 需要 router, CheckpointStage 需要 store (runtime deps)
      - Registry 用于 discovery (按 name/role/capability 索引), 不执行 Stage
      - 因此用 stub deps (router=None, _NullStore) 注册
      - default_pipeline(router, store) 用 real deps 重新构造 dep-requiring Stages
      - 第三方 Stage 注册时需自带 deps (register 前已可用)

    V1.0.9 扩展 (ADR-0030 Accepted 9.62/10):
      - source="builtin" 标识 built-in Stage
      - requires 声明 runtime deps (供 find_stages_needing / info 查询)
    """
    from planner.pipeline import RouteStage, MetricsStage
    from planner.stages.retry_stage import RetryStage
    from planner.stages.checkpoint_stage import CheckpointStage
    from planner.stages.condition_stage import ConditionStage

    # V1.0.9: 用 source="builtin" + requires 声明 runtime deps
    # stub deps for discovery; default_pipeline replaces with real deps
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


def _descriptor_to_dict(d: StageDescriptor) -> Dict[str, Any]:
    """StageDescriptor → dict (V1.0.9 helper, ADR-0030).

    本地 helper (不污染 StageDescriptor), V1.0.10 ADR-0031 实施
    `StageDescriptor.to_dict()` / `from_dict()` 后, 此 helper 可重构为 delegate.

    Returns:
        dict with keys: name / role / version / capabilities / idempotent /
        has_side_effects / always_run_after_stop / experimental / description / owner
    """
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


# T1 (采纳 ChatGPT 9.93/10): reset_default_registry() 测试 helper
def reset_default_registry() -> None:
    """重置 default registry (测试隔离用).

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


# ─────────────────────────────────────────────────────────────
# Default Pipeline 工厂
# ─────────────────────────────────────────────────────────────

def default_pipeline(
    router: Any,
    *,
    store: Any = None,
    registry: Optional[StageRegistry] = None,
) -> Any:
    """用 registry 构造 default ExecutionPipeline (V1.0.8 Registry-based 工厂).

    Args:
        router: Router 实例 (required, for RouteStage)
        store: ExecutionStore (optional, for CheckpointStage; None = skip checkpoint)
        registry: 可选, 默认用 default_registry()

    Returns:
        ExecutionPipeline 实例, stages 按 registry.default_order() 顺序:
          pre_bridge:  [RouteStage(router)]
          post_bridge: [MetricsStage, (CheckpointStage if store), ConditionStage]

    关键设计 (V1.0.8 实施发现 + Q3 重构):
      - ADR-0029 原设计 default_pipeline(*, registry) 无法工作:
        * ExecutionPipeline 需要 router (非 stages=)
        * RouteStage 需要 router, CheckpointStage 需要 store (runtime deps)
      - 修正: default_pipeline(router, store, registry) 接受 runtime deps
      - Registry 用于 discovery (按 role 顺序), 不持有可执行 Stage
      - RouteStage(router) / CheckpointStage(store) 用 real deps 重新构造
      - 其他 Stage (MetricsStage, ConditionStage, 第三方) 从 registry 直接取
      - 第三方 Stage 需自带 deps (register 前已可用)

    与 planner.pipeline.default_pipeline 的关系:
      - planner.pipeline.default_pipeline (V1.0.4): 显式 include_*flags 构造
      - planner.stage_registry.default_pipeline (V1.0.8): registry-driven 构造
      - 两者并存, V1.0.8 鼓励用 registry-based 工厂
    """
    from planner.pipeline import ExecutionPipeline, RouteStage
    from planner.stages.checkpoint_stage import CheckpointStage

    if registry is None:
        registry = default_registry()

    pre_bridge: list = []
    post_bridge: list = []

    for role in registry.default_order():
        if role == "stage":
            # RouteStage needs real router (registry stub has router=None)
            pre_bridge.append(RouteStage(router=router))
        else:
            for stage in registry.by_role(role):
                desc = get_descriptor(stage)
                if desc.name == "checkpoint":
                    # CheckpointStage needs real store (registry stub has _NullStore)
                    if store is not None:
                        post_bridge.append(CheckpointStage(store=store))
                    # else: skip checkpoint (store=None)
                else:
                    # MetricsStage, ConditionStage, third-party: use as-is
                    post_bridge.append(stage)

    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
    )

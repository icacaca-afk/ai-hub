# AI Hub — StageDescriptor
# V1.0.6: Stage 元数据描述对象 (ADR-0026 ChatGPT 9.94/10 FINAL APPROVED)
#
# StageDescriptor 是什么:
#   - Stage 的元数据 (Metadata)
#   - 描述: 名字 / 版本 / 角色 / 能力 / 副作用特征
#   - 与 Stage 实例解耦 (1:1 but separate)
#
# 关键设计原则 (ChatGPT 9.94/10):
#   ① frozen=True 不可变
#     - Descriptor 是元数据, 不应被运行时修改
#   ② Capabilities 用 Set[str] (语义标签无重复)
#   ③ always_run_after_stop 单一行为信号 (Behavior > taxonomy)
#   ④ role 字符串 (V1.0.6), V2 转 Enum
#   ⑤ built-in Stage 必须显式 descriptor (Critical Q7)
#     - hasattr(stage, "store") duck typing 被拒绝
#     - 兼容性 helper 仅给 user plugin / legacy extension
#
# 关键不变量 (Runtime Contract §9.1):
#   - StageDescriptor MUST 是 frozen dataclass
#   - StageDescriptor MUST 有 name / version / role 字段
#   - StageDescriptor MUST NOT 在运行时被修改
#   - built-in Stage MUST 显式定义 descriptor (V1.0.6 Critical)
#   - user plugin / legacy Stage 可省略 descriptor (用 default_factory 兜底)
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, field
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, Protocol, runtime_checkable

if TYPE_CHECKING:
    # V1.0.6: 用 TYPE_CHECKING 消除循环依赖 (ChatGPT 9.95/10 Q4 采纳)
    # stage_descriptor.py 不再 runtime 依赖 pipeline.py
    from planner.pipeline import ExecutionContext


# ─────────────────────────────────────────────────────────────
# Stage Protocol (V1.0.6)
# ─────────────────────────────────────────────────────────────

@runtime_checkable
class Stage(Protocol):
    """Stage 接口约定 (V1.0.6 Protocol, 非继承要求).

    任何满足此协议的对象都是 Stage:
      - 有 `descriptor: StageDescriptor` 属性
      - 有 `__call__(ctx) -> ExecutionContext` 方法

    ChatGPT 9.94/10 Q4 采纳: Protocol 优于基类.
      原因: 当前架构刻意避免继承, Stage 已用 structural typing.
      Protocol 保留这一哲学, 不 nudge 用户走向继承.
    """
    descriptor: "StageDescriptor"

    def __call__(self, ctx: "ExecutionContext") -> "ExecutionContext": ...


# ─────────────────────────────────────────────────────────────
# StageDescriptor (V1.0.6)
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageDescriptor:
    """Stage 元数据描述 (V1.0.6).

    关键字段分类 (ChatGPT 9.94/10 Q1):
      V1.0.6 Core (驱动 Runtime 行为):
        - name / role / idempotent / has_side_effects / always_run_after_stop
      V1.x Metadata (informational):
        - description / version / experimental / owner
      V2 (Capabilities):
        - capabilities (V2 Stage Registry / Plugin / UI 消费)

    Attributes:
        name: 唯一 ID, e.g. "route" / "metrics" / "checkpoint"
        version: Stage 版本 (V1.0.6: 1)
        role: 语义角色, V1.0.6 字符串 ("stage" | "checkpoint" | "condition" |
            "retry" | "metric"), V2 转 Enum
        capabilities: 能力标签 FrozenSet[str] (V2 消费, 语义标签无重复)
        idempotent: 多次执行是否安全
        has_side_effects: 是否修改外部状态 (e.g. 写 ExecutionStore / 调 Provider)
        always_run_after_stop: 即使 ctx.stop=True 仍执行 (V1.0.4 Checkpoint 关键)
        experimental: 是否实验性 (Hook 可见)
        description: 人类可读描述
        owner: 维护者
    """

    # 必填: 身份
    name: str

    # V1.0.6 Core
    role: str = "stage"
    idempotent: bool = True
    has_side_effects: bool = False
    always_run_after_stop: bool = False

    # V1.x Metadata
    version: int = 1
    description: str = ""
    owner: str = "ai-hub"
    experimental: bool = False

    # V2 (capabilities 保留 dataclass, Runtime Contract 不依赖)
    capabilities: FrozenSet[str] = field(default_factory=frozenset)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict (V1.0.10, ADR-0031).

        Delegate to ``planner.metadata_serialization.serialize_descriptor``.
        R1 (ChatGPT 9.6/10): this method is a facade; canonical logic lives
        in ``serialize_descriptor()``.

        Returns:
            dict (schema see ADR-0031 §2.1)
        """
        from planner.metadata_serialization import serialize_descriptor
        return serialize_descriptor(self)


# ─────────────────────────────────────────────────────────────
# get_descriptor() — 兼容 helper (仅给 user plugin / legacy)
# ─────────────────────────────────────────────────────────────

def get_descriptor(stage: Any) -> StageDescriptor:
    """V1.0.6: 提取 Stage Descriptor, 兼容 V1.0.x 旧 Stage.

    关键约束 (ChatGPT 9.94/10 Q7 Critical):
      - built-in Stage 全部显式 descriptor, 此 helper 仅给:
        * user plugin
        * legacy extension (V1.0.5 之前用户自定义的 Stage)
      - 绝不推断 checkpoint 语义 (不再 hasattr(stage, "store") 探测).
      - 绝不基于 stage.name 字符串识别角色.
      - 绝不返回带 always_run_after_stop=True 的默认 Descriptor.

    Args:
        stage: 任何对象 (Stage / user plugin / legacy extension)

    Returns:
        StageDescriptor 实例
          - 如果 stage 有 descriptor 属性: 返回 stage.descriptor
          - 否则: 返回默认 StageDescriptor(name=stage.name)
    """
    # 优先用显式 descriptor (built-in Stage 必有)
    if hasattr(stage, "descriptor") and isinstance(stage.descriptor, StageDescriptor):
        return stage.descriptor

    # Fallback: 仅给 user plugin / legacy
    name = getattr(stage, "name", "stage")
    return StageDescriptor(name=name)


# ─────────────────────────────────────────────────────────────
# _STAGE_ROLE_MAP — V1.0.11 ADR-0032
# ─────────────────────────────────────────────────────────────

_STAGE_ROLE_MAP: Dict[str, str] = {
    "RouteStage": "router",
    "MetricsStage": "metrics",
    "RetryStage": "retry",
    "ConditionStage": "condition",
    "CheckpointStage": "checkpoint",
}


# ─────────────────────────────────────────────────────────────
# StageDescriptor.from_stage() — V1.0.11 ADR-0032
# ─────────────────────────────────────────────────────────────


@classmethod  # type: ignore[misc]
def from_stage(
    cls,
    stage: Any,
    position: str = "",
    index: int = -1,
) -> "StageDescriptor":
    """从 Stage 实例推断描述信息 (V1.0.11 ADR-0032).

    推断规则:
      - name: stage.name 或 stage.__class__.__name__.lower()
      - role: 基于 Stage 类型 (type(stage).__name__), 不基于 name
      - requires/provides: frozenset() (不猜)
      - description: "" (不猜)
      - 未识别类型: role="unknown"

    Unknown ≠ invalid, Unknown = introspectable but unclassified.

    Args:
        stage: ExecutionStage Protocol 实例
        position: "pre" | "post" | "" (仅 informational)
        index: 在 position 列表中的索引 (仅 informational)

    Returns:
        StageDescriptor 实例
    """
    # name: 优先用 stage.name, fallback 用类名
    name = getattr(stage, "name", None)
    if name is None:
        name = type(stage).__name__.lower()

    # role: 基于类型, 不基于 name (ChatGPT P0: name 是 display identity)
    stage_type = type(stage).__name__
    role = _STAGE_ROLE_MAP.get(stage_type, "unknown")

    return cls(
        name=name,
        role=role,
    )


# 挂载到 StageDescriptor 类上
StageDescriptor.from_stage = from_stage


# ─────────────────────────────────────────────────────────────
# Module API
# ─────────────────────────────────────────────────────────────

__all__ = [
    "Stage",
    "StageDescriptor",
    "get_descriptor",
]

# AI Hub — Runtime Metadata (V1.0.7, ADR-0027 Accepted 9.85/10)
#
# 运行时元数据容器 (强类型) + 写穿 helper (采纳 ChatGPT 9.85/10 N1).
#
# 关键设计 (采纳 ChatGPT 9.2/10 Q4 additive migration + 9.85/10 N1 helper):
#   ① RuntimeMetadata 强类型 dataclass (替代 dict 字符串 key)
#   ② ExecutionContext 保留 ctx.metadata: dict (V1.0.6 行为不变)
#   ③ ExecutionContext 新增 ctx.runtime: RuntimeMetadata (新字段)
#   ④ Stage 通过 helper.set_*() 双写 runtime + metadata
#   ⑤ helper 封装双写, Stage 不散落双写逻辑 (V2 移除 metadata 兼容时只改 helper)
#   ⑥ write-through ONLY: runtime → metadata (单向, 不做反向同步)
#   ⑦ custom 命名空间受控 (第三方 Stage 写 ctx.runtime.custom["my_plugin"])
#   ⑧ stopped_by 顶级字段 (V1.0.4 嵌套在 condition_eval.stopped_by, V1.0.7 提升顶级)
#
# 字段集 (V1.0.7 MUST):
#   - server_metrics: Dict[str, Any]   (MetricsStage 写)
#   - condition_eval: Optional[ConditionEval]  (ConditionStage 写, CheckpointStage 读)
#   - stopped_by: Optional[str]         (顶级字段, ChatGPT 9.2/10 关键采纳)
#   - plan: Dict[str, int]              (PlanExecutor 写)
#   - custom: Dict[str, Any]            (user plugin 写)
#
# 字段集 NOT in V1.0.7 (采纳 ChatGPT 9.2/10):
#   - retry: V1.1 再加
#   - experimental: V2 再加
#   - schema_version: V1.0.8 再加
#
# Runtime Contract MUST (采纳 ChatGPT 9.85/10):
#   - RuntimeMetadata MUST be the canonical source for all built-in runtime state.
#   - metadata compatibility is write-through only (runtime → metadata, NOT reverse).
#   - RuntimeMetadata is additive and MUST NOT invalidate any existing metadata usage during V1.x.
#   - ctx.metadata support is permanent during V1.x (no warning, no deprecation).
#
# API Stability: Experimental

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, Optional

if TYPE_CHECKING:
    from planner.pipeline import ExecutionContext
    from planner.stages.condition_stage import ConditionEval

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# V1.0.7 reserved namespace (Runtime Contract §10 文档化)
# ─────────────────────────────────────────────────────────────

RUNTIME_RESERVED_KEYS: FrozenSet[str] = frozenset({
    "server_metrics",
    "condition_eval",
    "stopped_by",
    "plan",
    "custom",
})


def _ensure_metadata(ctx: "ExecutionContext") -> dict:
    """确保 ctx.metadata 是 dict (V1.0.6 行为兼容).

    V1.0.6 行为: ctx.metadata 是动态注入的属性, 首次写入时通过 setattr 创建.
    V1.0.7 保留: helper 写入前 ensure metadata 存在.
    """
    if not hasattr(ctx, "metadata") or ctx.metadata is None:
        ctx.metadata = {}
    return ctx.metadata


# ─────────────────────────────────────────────────────────────
# RuntimeMetadata — 强类型 dataclass + 写穿 helper
# ─────────────────────────────────────────────────────────────

@dataclass
class RuntimeMetadata:
    """运行时元数据容器 (V1.0.7 — additive migration).

    v2 关键设计 (采纳 ChatGPT 9.2/10 Q4 + 9.85/10 N1):
      - 强类型属性 (渐进引入, 不破坏 V1.0.6 dict API)
      - V1.0.7 MUST: server_metrics / condition_eval / stopped_by / plan / custom
      - V1.1: 加 retry (deferred, ChatGPT 9.2/10)
      - V2: 加 experimental (deferred, ChatGPT 9.2/10)
      - V1.0.8: 评估 schema_version (deferred, ChatGPT 9.85/10)
      - 允许 user plugin 写 custom.* 字段 (受控 namespace)

    Stage 调用 helper.set_*() 双写:
      - 写 self.<field> (强类型)
      - 写 ctx.metadata["<field>"] (V1.0.6 兼容)
      - V2 移除 metadata 兼容时只改 helper 内部

    Write-through ONLY (ChatGPT 9.85/10 MUST-2):
      - helper 写 runtime → metadata
      - 第三方 Stage 写 ctx.metadata["custom"] = X **不会**自动同步到 runtime
      - 避免双向同步 Bug
    """

    # V1.0.7 MUST: server metrics (MetricsStage 写)
    server_metrics: Dict[str, Any] = field(default_factory=dict)

    # V1.0.7 MUST: condition eval (ConditionStage 写, CheckpointStage 读)
    condition_eval: Optional["ConditionEval"] = None

    # V1.0.7 MUST: stopped_by 顶级字段 (ChatGPT 9.2/10 关键采纳)
    # 不再嵌套在 condition_eval 下, 与 condition_eval 平级
    # 未来 Retry / ManualAbort / Timeout / Cancellation / Hook 都可 stop
    stopped_by: Optional[str] = None

    # V1.0.7 MUST: plan aggregation (PlanExecutor 写)
    plan: Dict[str, int] = field(default_factory=dict)
    # e.g. {"success": 3, "failed": 1, "skipped": 0, "total": 4}

    # V1.0.7 MUST: user plugin namespace (受控前缀)
    custom: Dict[str, Any] = field(default_factory=dict)
    # 第三方 Stage 写入: ctx.runtime.custom["my_plugin"] = {...}

    # ─────────────────────────────────────────────────────
    # Helper 方法 (采纳 ChatGPT 9.85/10 N1)
    # 集中封装双写逻辑, Stage 不散落双写
    # ─────────────────────────────────────────────────────

    def set_condition_eval(
        self,
        eval: "ConditionEval",
        *,
        ctx: Optional["ExecutionContext"] = None,
    ) -> None:
        """设置 condition_eval (write-through to ctx.metadata).

        行为:
          - 写 self.condition_eval = eval (强类型)
          - 如果 eval.stopped_by is not None, 写 self.stopped_by = eval.stopped_by
          - 如果 ctx is not None, 同步写 ctx.metadata["condition_eval"] 和 ctx.metadata["stopped_by"]
            (V1.0.6 兼容)

        Stage 调用: ctx.runtime.set_condition_eval(eval, ctx=ctx)
        """
        self.condition_eval = eval
        if eval.stopped_by is not None:
            self.stopped_by = eval.stopped_by
        if ctx is not None:
            metadata = _ensure_metadata(ctx)
            metadata["condition_eval"] = eval.to_dict()
            if eval.stopped_by is not None:
                metadata["stopped_by"] = eval.stopped_by

    def set_server_metrics(
        self,
        metrics: Dict[str, Any],
        *,
        ctx: Optional["ExecutionContext"] = None,
        merge: bool = True,
    ) -> None:
        """设置 server_metrics (write-through to ctx.metadata).

        行为:
          - 写 self.server_metrics (默认 merge, 也可 replace)
          - 如果 ctx is not None, 同步写 ctx.metadata["server_metrics"]

        Args:
            metrics: 新的 server metrics dict
            ctx: ExecutionContext (用于 write-through, 可选)
            merge: True 合并到现有, False 替换

        Stage 调用: ctx.runtime.set_server_metrics(new_metrics, ctx=ctx)
        """
        if merge:
            self.server_metrics = {**self.server_metrics, **metrics}
        else:
            self.server_metrics = dict(metrics)
        if ctx is not None:
            metadata = _ensure_metadata(ctx)
            existing = metadata.get("server_metrics", {})
            if not isinstance(existing, dict):
                existing = {}
            metadata["server_metrics"] = {**existing, **metrics} if merge else dict(metrics)

    def set_plan(
        self,
        plan: Dict[str, int],
        *,
        ctx: Optional["ExecutionContext"] = None,
    ) -> None:
        """设置 plan aggregation (write-through to ctx.metadata).

        行为:
          - 写 self.plan = plan
          - 如果 ctx is not None, 同步写 ctx.metadata["plan"]

        Stage 调用: ctx.runtime.set_plan(aggregated, ctx=ctx)
        """
        self.plan = dict(plan)
        if ctx is not None:
            metadata = _ensure_metadata(ctx)
            metadata["plan"] = dict(plan)

    def set_stopped_by(
        self,
        stopped_by: str,
        *,
        ctx: Optional["ExecutionContext"] = None,
    ) -> None:
        """设置 stopped_by 顶级字段 (write-through to ctx.metadata).

        用于未来 Retry / ManualAbort / Timeout / Cancellation / Hook 等非 Condition stop.

        行为:
          - 写 self.stopped_by = stopped_by
          - 如果 ctx is not None, 同步写 ctx.metadata["stopped_by"]
        """
        self.stopped_by = stopped_by
        if ctx is not None:
            metadata = _ensure_metadata(ctx)
            metadata["stopped_by"] = stopped_by

    def set_custom(self, key: str, value: Any) -> None:
        """user plugin 写入 custom namespace (新 API, 不走 metadata 兼容).

        第三方 Stage 调用: ctx.runtime.custom["my_plugin"] = value (直接属性访问)
        或: ctx.runtime.set_custom("my_plugin", value) (helper)
        """
        self.custom[key] = value

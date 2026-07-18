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

    # ─────────────────────────────────────────────────────────
    # V1.0.8 新增: 5 个核心 getter (采纳 ChatGPT 9.91/10)
    # 统一访问接口, 替代散落属性访问
    # ─────────────────────────────────────────────────────────

    def get_stop_reason(self) -> Optional[str]:
        """获取停止原因 (顶级 stopped_by).

        Returns:
            stopped_by 字符串 (e.g. "condition:c1:skip", "retry:exhausted")
            None 表示未停止 (正常完成)
        """
        return self.stopped_by

    def get_metrics(self) -> Dict[str, Any]:
        """获取 server metrics (返回 copy 避免外部修改).

        Returns:
            server_metrics dict (默认空 dict, never None)
        """
        return dict(self.server_metrics)

    def get_condition(self) -> Optional["ConditionEval"]:
        """获取最后一次 condition eval.

        Returns:
            ConditionEval 实例 (ConditionStage 写入)
            None 表示未执行 condition
        """
        return self.condition_eval

    def get_plan_progress(self) -> Dict[str, int]:
        """获取 plan 聚合进度 (返回 copy).

        Returns:
            plan dict, e.g. {"success": 3, "failed": 1, "total": 4}
            默认空 dict
        """
        return dict(self.plan)

    def get_custom(self, name: str, default: Any = None) -> Any:
        """获取 user plugin 命名空间数据 (返回引用, 允许修改).

        注意: 与 get_metrics()/get_plan_progress() 不同, custom 返回引用
        因为 plugin namespace 设计上就是允许修改的.

        Args:
            name: plugin 名称 (e.g. "my_plugin")
            default: 默认值, 找不到时返回 (默认 None)

        Returns:
            plugin 写入的数据
            未找到返回 default
        """
        return self.custom.get(name, default)

    # ─────────────────────────────────────────────────────────
    # V1.0.8 新增: 5 个 has_xxx() 方法 (采纳 ChatGPT 9.91/10 Non-blocking)
    # API Human Factor: 比 if get_xxx() is not None 可读性更好
    # ─────────────────────────────────────────────────────────

    def has_stop_reason(self) -> bool:
        """是否有停止原因 (顶级 stopped_by)."""
        return self.stopped_by is not None

    def has_metrics(self) -> bool:
        """是否有 server metrics (非空 dict)."""
        return bool(self.server_metrics)

    def has_condition(self) -> bool:
        """是否执行过 condition (ConditionEval 不为 None)."""
        return self.condition_eval is not None

    def has_plan_progress(self) -> bool:
        """是否有 plan 聚合进度 (非空 dict)."""
        return bool(self.plan)

    def has_custom(self, name: str) -> bool:
        """是否有指定 plugin 数据.

        Args:
            name: plugin 名称

        Returns:
            True 如果 custom[name] 存在
        """
        return name in self.custom

    # ─────────────────────────────────────────────────────────
    # V1.0.8 新增: resolve_stop_reason (采纳 ChatGPT 9.88/10 Q3 + 9.91/10 命名一致)
    # 命名变更: resolve_stopped_by → resolve_stop_reason (与 get_stop_reason 一致)
    # 封装 4 级优先级查找, CheckpointStage 改用此方法 (净减代码)
    # ─────────────────────────────────────────────────────────

    def resolve_stop_reason(self, ctx: "ExecutionContext") -> Optional[str]:
        """解析停止原因 (4 级优先级查找, 封装 V1.0.7 内联逻辑).

        优先级 (V1.0.7 行为, 封装到 RuntimeMetadata):
          1. self.stopped_by (顶级字段, V1.0.7 新 API)
          2. self.condition_eval.stopped_by (V1.0.7 强类型)
          3. ctx.metadata["condition_eval"]["stopped_by"] (V1.0.6 dict 兼容)
          4. ctx.stop → "stop_flag" (兜底)

        未来扩展 (V1.x / V2):
          - RetryStage: 写 self.stopped_by = "retry:exhausted"
          - Timeout: 写 self.stopped_by = "timeout:30s"
          - Cancellation: 写 self.stopped_by = "cancellation:user"
          - Hook: 写 self.stopped_by = "hook:my_hook"
          - Manual Abort: 写 self.stopped_by = "manual:user_id"

        Args:
            ctx: ExecutionContext (用于读取 metadata 兜底)

        Returns:
            stopped_by 字符串 或 None (未停止)
        """
        # 优先级 1: 顶级 stopped_by
        if self.stopped_by is not None:
            return self.stopped_by
        # 优先级 2: condition_eval.stopped_by
        if self.condition_eval is not None and self.condition_eval.stopped_by is not None:
            return self.condition_eval.stopped_by
        # 优先级 3: ctx.metadata["condition_eval"] dict 兜底
        ctx_metadata = getattr(ctx, "metadata", None) or {}
        if isinstance(ctx_metadata, dict):
            condition_eval = ctx_metadata.get("condition_eval")
            if isinstance(condition_eval, dict):
                stopped_by = condition_eval.get("stopped_by")
                if stopped_by:
                    return stopped_by
        # 优先级 4: ctx.stop → "stop_flag"
        if getattr(ctx, "stop", False):
            return "stop_flag"
        return None

    # V1.0.7 → V1.0.8 命名过渡: resolve_stopped_by 别名 (保留向后兼容)
    # 第三方代码可能用了 resolve_stopped_by, 保留别名避免 breaking
    resolve_stopped_by = resolve_stop_reason  # alias for backward compat

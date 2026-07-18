# AI Hub — PipelineHooks
# V1.0.5: Pipeline 生命周期观察器 (Lifecycle Observer) (ADR-0025 ChatGPT 9.9/10 FINAL APPROVED)
#
# Hook 是 Observer, 不是 Stage.
# Hook 关注: 生命周期事件 (Lifecycle Events).
# Hook 不关注: 数据 / 业务逻辑 / 控制流.
#
# 关键设计原则 (ChatGPT 9.9/10):
#   ① Hook is an observer, not a Stage
#     - 负责: 观察
#     - 不负责: 修改 ctx / 控制流 / 业务逻辑
#   ② Hook MUST be observational and MUST NOT participate in execution semantics
#     - 永远 Callable(...)->None
#     - 不返回修改后的 ctx
#   ③ Hook failures MUST NOT influence execution outcome
#     - 即使所有 hook 都失败, Pipeline 仍应正常执行
#   ④ Hooks SHOULD execute in registration order (FIFO)
#   ⑤ Hooks SHOULD be side-effect free whenever practical
#
# 6 类 Hook 点:
#   - before_pipeline: Pipeline.run 入口
#   - after_pipeline: Pipeline.run 出口
#   - before_stage: 每个 Stage 前
#   - after_stage: 每个 Stage 后
#   - on_error: Stage 异常时
#   - on_stop: ctx.stop 触发时
#
# API Stability: Experimental

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from planner.pipeline import ExecutionContext
from core.result import Result

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Hook 类型 (V1.0.5)
# ─────────────────────────────────────────────────────────────

# Before Pipeline Hook (整体执行前)
BeforePipelineHook = Callable[[ExecutionContext], None]

# After Pipeline Hook (整体执行后, 含 Result)
AfterPipelineHook = Callable[[ExecutionContext, Result], None]

# Before Stage Hook (每个 Stage 前)
# V1.0.6: 加 descriptor 可选参数 (Backwards-compat)
# V1.0.5 旧 Hook: def before_stage(ctx, stage_name) -> None
# V1.0.6 新 Hook: def before_stage(ctx, stage_name, descriptor=None) -> None
BeforeStageHook = Callable[..., None]  # (ctx, stage_name, descriptor=None)

# After Stage Hook (每个 Stage 后)
AfterStageHook = Callable[..., None]  # (ctx, stage_name, descriptor=None)

# On Error Hook (Stage 异常时)
OnErrorHook = Callable[..., None]  # (ctx, stage_name, exc, descriptor=None)

# On Stop Hook (ctx.stop 触发时)
OnStopHook = Callable[[ExecutionContext, str], None]  # (ctx, stopped_by)


# ─────────────────────────────────────────────────────────────
# PipelineHooks — 6 类 Hook 集合
# ─────────────────────────────────────────────────────────────

class PipelineHooks:
    """V1.0.5: Pipeline 生命周期观察器 (Best Effort).

    关键不变量 (Runtime Contract §9.1.6):
      - Hook 异常 → 静默 (Best Effort, logger.warning)
      - Hook MUST NOT 修改 ExecutionContext
      - Hook MUST NOT 接触 SQLiteExecutionStore / EventBus 内部
      - Hook MUST NOT 抛异常
      - Hook MUST NOT 影响 Stage 行为
      - Hook 按 FIFO 顺序执行 (V1.0.5)
      - Hook 应当 side-effect free

    6 类 Hook 点:
      - before_pipeline: Pipeline.run 入口
      - after_pipeline: Pipeline.run 出口
      - before_stage: 每个 Stage 前
      - after_stage: 每个 Stage 后
      - on_error: Stage 异常时
      - on_stop: ctx.stop 触发时

    API Stability: Experimental
    """

    def __init__(
        self,
        before_pipeline: Optional[list[BeforePipelineHook]] = None,
        after_pipeline: Optional[list[AfterPipelineHook]] = None,
        before_stage: Optional[list[BeforeStageHook]] = None,
        after_stage: Optional[list[AfterStageHook]] = None,
        on_error: Optional[list[OnErrorHook]] = None,
        on_stop: Optional[list[OnStopHook]] = None,
    ):
        self.before_pipeline = list(before_pipeline or [])
        self.after_pipeline = list(after_pipeline or [])
        self.before_stage = list(before_stage or [])
        self.after_stage = list(after_stage or [])
        self.on_error = list(on_error or [])
        self.on_stop = list(on_stop or [])

    @property
    def enabled(self) -> bool:
        """是否启用 (即有任一 hook 注册).

        ChatGPT 9.9/10 Q7 采纳: 替代 is_empty() 内部 list 检查.
        Pipeline.run() 可用 if hooks.enabled: fire(...) 短路.
        """
        return any([
            self.before_pipeline,
            self.after_pipeline,
            self.before_stage,
            self.after_stage,
            self.on_error,
            self.on_stop,
        ])

    def is_empty(self) -> bool:
        """V1.0.5: 兼容旧 API, 等价于 not enabled."""
        return not self.enabled

    # ── Hook 触发器 (Best Effort) ──

    def fire_before_pipeline(self, ctx: ExecutionContext) -> None:
        """触发 before_pipeline hooks (Best Effort)."""
        for hook in self.before_pipeline:
            try:
                hook(ctx)
            except Exception as e:
                logger.warning("before_pipeline hook raised: %s", e)

    def fire_after_pipeline(self, ctx: ExecutionContext, result: Result) -> None:
        """触发 after_pipeline hooks (Best Effort)."""
        for hook in self.after_pipeline:
            try:
                hook(ctx, result)
            except Exception as e:
                logger.warning("after_pipeline hook raised: %s", e)

    def fire_before_stage(
        self, ctx: ExecutionContext, stage_name: str, descriptor: Any = None
    ) -> None:
        """触发 before_stage hooks (Best Effort).

        V1.0.6: descriptor 是可选参数, 旧 Hook (V1.0.5 接受 (ctx, stage_name)) 仍可工作.
        """
        for hook in self.before_stage:
            try:
                # V1.0.6: 智能调用 — 旧 Hook 不传 descriptor, 新 Hook 收 descriptor
                try:
                    hook(ctx, stage_name, descriptor=descriptor)
                except TypeError:
                    # 旧 Hook 不接受 descriptor 参数
                    hook(ctx, stage_name)
            except Exception as e:
                logger.warning("before_stage hook raised: %s", e)

    def fire_after_stage(
        self, ctx: ExecutionContext, stage_name: str, descriptor: Any = None
    ) -> None:
        """触发 after_stage hooks (Best Effort).

        V1.0.6: descriptor 是可选参数, 旧 Hook 仍可工作.
        """
        for hook in self.after_stage:
            try:
                try:
                    hook(ctx, stage_name, descriptor=descriptor)
                except TypeError:
                    hook(ctx, stage_name)
            except Exception as e:
                logger.warning("after_stage hook raised: %s", e)

    def fire_on_error(
        self,
        ctx: ExecutionContext,
        stage_name: str,
        exc: Exception,
        descriptor: Any = None,
    ) -> None:
        """触发 on_error hooks (Best Effort).

        V1.0.6: descriptor 是可选参数, 旧 Hook 仍可工作.
        """
        for hook in self.on_error:
            try:
                try:
                    hook(ctx, stage_name, exc, descriptor=descriptor)
                except TypeError:
                    hook(ctx, stage_name, exc)
            except Exception as e:
                logger.warning("on_error hook raised: %s", e)

    def fire_on_stop(self, ctx: ExecutionContext, stopped_by: str) -> None:
        """触发 on_stop hooks (Best Effort).

        Args:
            ctx: ExecutionContext
            stopped_by: 终止来源 (e.g. "condition:on_failure:abort" / "stop_flag")
        """
        for hook in self.on_stop:
            try:
                hook(ctx, stopped_by)
            except Exception as e:
                logger.warning("on_stop hook raised: %s", e)

    def __repr__(self) -> str:
        return (
            f"PipelineHooks("
            f"before_pipeline={len(self.before_pipeline)}, "
            f"after_pipeline={len(self.after_pipeline)}, "
            f"before_stage={len(self.before_stage)}, "
            f"after_stage={len(self.after_stage)}, "
            f"on_error={len(self.on_error)}, "
            f"on_stop={len(self.on_stop)})"
        )

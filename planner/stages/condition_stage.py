# AI Hub — ConditionStage
# V1.0.4: Pipeline Workflow Control (Control Boundary) (ADR-0024 ChatGPT 9.9/10 FINAL APPROVED)
#
# 验证 Pipeline 第四个 Stage: Condition 让 Pipeline 真正成为 Workflow Runtime.
#
# 关键设计原则 (ChatGPT 9.9/10):
#   ① Condition is a control boundary, not a data boundary
#     - 负责: 控制 (continue/skip/abort)
#     - 不负责: 数据 (不修改 ctx.task / ctx.bridge_result)
#   ② Condition is a callable, not a DSL
#     - V1.0.4 仅 Callable[[ExecutionContext], bool]
#     - 不做 DSL / JSON Schema / YAML
#   ③ Fail-Closed
#     - Condition 异常 -> 视为 False -> 继续执行
#     - 不允许: Condition 异常 -> Pipeline FAIL
#
# Stage 顺序 (默认):
#   [RetryStage, MetricsStage, ConditionStage, CheckpointStage]
#   - Condition 在 Checkpoint 前: 终止决策先写入 metadata
#   - Condition 在 Metrics 后: 终止决策基于最终结果 (含重试后 + metrics 注入后)
#   - Checkpoint 总是写: 即使 abort 也要写 (记录 Runtime 事实)
#
# 三个动作 (ChatGPT 9.9/10 Q3 关键澄清):
#   - continue: 继续执行后续 Stage
#   - skip: 跳过后续 Stage (视为 Workflow 正常结束)
#   - abort: 主动终止 Workflow (紧急停止)
#   - skip vs abort 区别: metadata.stopped_by = "condition:skip" / "condition:abort"
#
# 关键不变量 (来自 Runtime Contract §9.1.5):
#   - MUST NOT 修改 ExecutionContext 主体 (仅在 skip/abort 时设 ctx.stop)
#   - MUST 接受 Callable[[ExecutionContext], bool] 作为 condition
#   - MUST condition 求值 -> 按 on_true/on_false 决定动作
#   - MUST 在 action="skip"/"abort" 时设置 ctx.stop = True
#   - MUST condition 异常 -> fail-closed (视为 False)
#   - MUST Stage 自身异常 -> return ctx (Best Effort)
#   - MUST 求值结果写入 ctx.metadata["condition_eval"]
#   - MUST condition 是 deterministic (不应使用 random/time/network)
#   - MUST NOT 修改 ctx.task / ctx.bridge_result / ctx.provider
#   - MUST NOT 接触 SQLiteExecutionStore / EventBus 内部
#   - MUST NOT 抛异常
#
# API Stability: Experimental

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from planner.pipeline import ExecutionContext
from planner.stage_descriptor import StageDescriptor

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Condition 类型 (ChatGPT 9.9/10 Q2 关键)
# ─────────────────────────────────────────────────────────────

# Condition is a callable, not a DSL.
# V1.0.4 仅 Callable[[ExecutionContext], bool]
# 不做 DSL / JSON Schema / YAML (V1.1 评估)
Condition = Callable[[ExecutionContext], bool]

VALID_ACTIONS = ("continue", "skip", "abort")


# ─────────────────────────────────────────────────────────────
# ConditionEval — 审计元数据
# ─────────────────────────────────────────────────────────────

@dataclass
class ConditionEval:
    """Condition 求值审计 (V1.0.4).

    写入 ctx.metadata["condition_eval"], 供后续 Stage (特别是 Checkpoint) 看到.
    """
    stage: str
    condition_name: str
    result: bool
    action: str
    timestamp: float
    stopped_by: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "condition_name": self.condition_name,
            "result": self.result,
            "action": self.action,
            "timestamp": self.timestamp,
            "stopped_by": self.stopped_by,
        }


# ─────────────────────────────────────────────────────────────
# ConditionStage — Runtime Stage
# ─────────────────────────────────────────────────────────────

class ConditionStage:
    """Post-bridge Stage: 条件分支 / 跳过 / 终止.

    关键不变量 (Runtime Contract §9.1.5):
      - 0 修改 ExecutionContext 主体 (仅在 skip/abort 时设 ctx.stop)
      - Condition 异常 -> fail-closed (视为条件不满足, 继续执行)
      - Stage 异常 -> return ctx (Best Effort)
      - 求值结果写入 ctx.metadata["condition_eval"]

    Stage 顺序 (默认):
      [RetryStage, MetricsStage, ConditionStage, CheckpointStage]
      - Condition 在中间: 终止决策基于最终结果
      - Checkpoint 总是写: 即使 abort 也要写 (Runtime Observability)

    API Stability: Experimental
    """

    # V1.0.6: 显式 StageDescriptor (ADR-0026 ChatGPT 9.94/10 Critical Q7)
    descriptor = StageDescriptor(
        name="condition",
        version=1,
        role="condition",
        capabilities=frozenset({"controls_flow"}),
        idempotent=True,
        has_side_effects=False,
        always_run_after_stop=False,
        description="Conditional branch: continue / skip / abort",
        owner="ai-hub",
        experimental=False,
    )

    def __init__(
        self,
        condition: Condition,
        on_true: str = "continue",
        on_false: str = "continue",
        name: str = "condition",
    ):
        """构造 ConditionStage.

        Args:
            condition: Callable[[ExecutionContext], bool] 条件
                       (None -> ValueError)
            on_true: condition=True 时的动作
                     ("continue" | "skip" | "abort")
            on_false: condition=False 时的动作
                      ("continue" | "skip" | "abort")
            name: Stage 名称 (用于 metadata 调试, 默认 "condition")

        Raises:
            ValueError: condition 为 None 或 on_true/on_false 非法
        """
        if condition is None:
            raise ValueError(
                "ConditionStage requires a non-None condition. "
                "Pass a callable: condition=lambda ctx: ctx.bridge_result.success"
            )
        if on_true not in VALID_ACTIONS:
            raise ValueError(
                f"ConditionStage on_true must be one of {VALID_ACTIONS}, got {on_true!r}"
            )
        if on_false not in VALID_ACTIONS:
            raise ValueError(
                f"ConditionStage on_false must be one of {VALID_ACTIONS}, got {on_false!r}"
            )

        self.condition = condition
        self.on_true = on_true
        self.on_false = on_false
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """求值 condition, 按 on_true/on_false 决定动作.

        短路条件 (直接 pass):
          - ctx.task is None
          - ctx.bridge_result is None
          - 注意: 不短路 ctx.stop (V1.0.4 调整, ChatGPT 9.9/10 Q4 关键)
            - 即使 ctx.stop=True 也要重新求值 condition (用户可能想覆盖)
            - 但实际上 Condition 是"主动终止机制", 被 stop 后再求值意义不大
            - 决定: ctx.stop=True 时仍求值, 但结果不影响 (因为下一 Stage Checkpoint 会写 aborted)

        行为:
          1. 求值 condition (fail-closed)
          2. 选择动作 (on_true 或 on_false)
          3. 写入 metadata["condition_eval"] (供 Checkpoint 看到)
          4. 执行动作 (skip/abort -> ctx.stop = True)

        Returns:
            ExecutionContext (可能设 ctx.stop = True)
        """
        # 短路: 仅 task / bridge_result 缺失时 pass
        if ctx.task is None or ctx.bridge_result is None:
            return ctx

        # 1. 求值 condition (fail-closed)
        try:
            result = bool(self.condition(ctx))
        except Exception as e:
            logger.warning(
                "ConditionStage condition raised exception for task %s: %s. "
                "Treating as False (fail-closed).",
                ctx.task.task_id, e,
            )
            result = False

        # 2. 选择动作
        action = self.on_true if result else self.on_false

        # 3. 写入审计
        stopped_by: Optional[str] = None
        if action == "skip":
            stopped_by = f"condition:{self._name}:skip"
        elif action == "abort":
            stopped_by = f"condition:{self._name}:abort"

        # 确保 ctx.metadata 存在 (向后兼容: ctx 可能没有 metadata 字段)
        if not hasattr(ctx, "metadata") or ctx.metadata is None:
            # 不可变 ctx, 但 __dict__ 可以扩展 (dataclass 是 frozen=False 默认)
            # 实际 ExecutionContext 不是 frozen, 所以可以直接 setattr
            ctx.metadata = {}

        # V1.0.7 (ADR-0027 Accepted 9.85/10): 强类型 + 双写 (helper.set_condition_eval)
        # 写 ctx.runtime.condition_eval (新) + ctx.runtime.stopped_by 顶级 (新)
        # 同时通过 helper write-through 写 ctx.metadata["condition_eval"] (旧 API, 兼容)
        # 关键: helper 内部完成双写, Stage 不散落双写逻辑 (ChatGPT 9.85/10 N1 采纳)
        ctx.runtime.set_condition_eval(
            ConditionEval(
                stage="condition",
                condition_name=self._name,
                result=result,
                action=action,
                timestamp=time.time(),
                stopped_by=stopped_by,
            ),
            ctx=ctx,
        )

        # 4. 执行动作
        if action in ("skip", "abort"):
            ctx.stop = True

        return ctx

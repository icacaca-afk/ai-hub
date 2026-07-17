# AI Hub — Plan / Step dataclass
# V0.9: 多步任务分解的数据载体
#
# Plan 是 Step 的有序集合，Step 是子任务的载体。
# Step 复用 Task 的字段语义（content/capabilities/context），但不继承 Task——
# 避免污染冻结的 Task 抽象（ADR-0008）。
#
# ADR-0013: V0.9.0 骨架。depends_on 字段仅记录不消费，为 V0.10+ DAG 留接口。
# ADR-0017: V0.9.4 events / execution_metrics 可选字段（Postel's Law 兼容）
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from core.result import Result


if TYPE_CHECKING:
    from planner.execution_metrics import ExecutionMetrics


@dataclass
class Step:
    """子任务载体。

    Plan 中的一个步骤，独立路由、独立执行。
    V0.9.0：depends_on 仅记录线性依赖，执行器不消费。
    V0.9.0：execution_result 字段名预留扩展，为 V0.10+ 重试/execution_history 留空间。
    V0.9.4：events / execution_metrics 可选字段（ADR-0017，Optional 保持向后兼容）

    API Stability: Experimental
    """

    step_id: str                                                # 形如 "step-0"
    content: str                                                # 子任务自然语言描述
    capabilities: list[str] = field(default_factory=list)       # 能力标签（由 classify 识别）
    depends_on: list[str] = field(default_factory=list)         # 依赖的前置 step_id（V0.9.0 仅记录）
    context: dict[str, Any] = field(default_factory=dict)       # 子任务上下文
    status: str = "pending"                                     # pending / running / success / failed / skipped
    execution_result: Optional[Result] = None                  # 执行后填入（为 V0.10+ 重试/execution_history 预留）
    # V0.9.4 (ADR-0017): 可选字段，老 consumer 缺字段静默忽略
    events: list["ExecutionEvent"] = field(default_factory=list)  # noqa: F821 — Step-level events
    execution_metrics: Optional["ExecutionMetrics"] = None      # Step-level 可测量指标

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "content": self.content,
            "capabilities": self.capabilities,
            "depends_on": self.depends_on,
            "status": self.status,
            "execution_result": self.execution_result.to_dict() if self.execution_result else None,
            "events": [e.to_dict() for e in self.events],
            "execution_metrics": self.execution_metrics.to_dict() if self.execution_metrics else None,
        }


@dataclass
class Plan:
    """Plan = 有序 Step 集合。

    由 Planner.decompose() 产生，由 PlanExecutor 顺序执行。

    V0.9.4 (ADR-0017): 增加 events / aggregate_metrics 字段。

    API Stability: Experimental
    """

    plan_id: str                                                # 唯一标识符
    task_id: str                                                # 关联的原 Task.task_id
    steps: list[Step]
    status: str = "pending"                                     # pending / running / success / partial / failed
    created_at: str = ""                                        # ISO 时间戳
    metadata: dict[str, Any] = field(default_factory=dict)
    # V0.9.4 (ADR-0017): 可选字段
    events: list["ExecutionEvent"] = field(default_factory=list)  # noqa: F821 — Plan-level events
    aggregate_metrics: "ExecutionMetrics" = field(default_factory=lambda: _default_metrics())  # Plan 聚合指标

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
            "events": [e.to_dict() for e in self.events],
            "aggregate_metrics": self.aggregate_metrics.to_dict(),
        }

    @property
    def step_count(self) -> int:
        return len(self.steps)


def _default_metrics():
    """延迟导入避免循环依赖（plan.py → execution_metrics.py 不应反向依赖）。"""
    from planner.execution_metrics import ExecutionMetrics
    return ExecutionMetrics()

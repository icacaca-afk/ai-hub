# AI Hub — Plan Executor
# V0.9.0: 顺序执行 Plan 中的 Step，聚合结果
#
# 通过组合持有 Router（不继承），对每个 Step 调 router.execute(sub_task)。
# ScoreRouter 的评分、Health 过滤、Quota 管理全部复用。
#
# ADR-0013: V0.9.0 只做顺序执行 + 简单聚合。DAG/并行留 V0.10+。
#
# 聚合规则（V0.9.0 极简）：
#   - 全 success → success
#   - 全 failed → failed
#   - 混合 → partial
#   - outputs 顺序拼接（带 step header），artifacts 合并去重
#
# API Stability: Experimental

from __future__ import annotations

from typing import Any, Optional

from core.result import Result
from core.task import Task
from planner.base import Planner
from planner.plan import Plan
from planner.rule_based_planner import RuleBasedPlanner
from router.router import Router


class PlanExecutor:
    """Plan 执行器。

    组合 Router + Planner，把复合 Task 分解后逐步执行并聚合。

    V0.9.0 范围：
        - 顺序执行（不消费 depends_on，不做拓扑排序）
        - 简单聚合（顺序拼接 outputs，合并 artifacts）
        - 不做并行、不做 LLM 总结

    未来扩展（不在此版本实现）：
        - V0.10+：消费 depends_on，做 DAG 拓扑排序 + 并行执行
        - V0.9.1+：LLM 总结（聚合 output 由 LLM 重写）

    API Stability: Experimental
    """

    def __init__(self, router: Router, planner: Optional[Planner] = None):
        self.router = router
        self.planner = planner or RuleBasedPlanner()
        self.last_plan: Optional[Plan] = None

    def execute(self, task: Task) -> Result:
        """分解 + 顺序执行 + 聚合。

        Args:
            task: 原始复合 Task

        Returns:
            聚合后的 Result（provider="planner"）
        """
        plan = self.planner.decompose(task)
        plan.status = "running"
        self.last_plan = plan

        for step in plan.steps:
            step.status = "running"
            sub_task = Task(
                content=step.content,
                capabilities=step.capabilities,
                context={**task.context, **step.context},
            )
            result = self.router.execute(sub_task)
            step.result = result
            step.status = "success" if result.is_success else "failed"

        return self._aggregate(plan, task)

    def _aggregate(self, plan: Plan, original_task: Task) -> Result:
        """聚合所有 Step 的结果。

        - status: 全 success→success / 全 failed→failed / 混合→partial
        - output: 顺序拼接，每段带 [Step i: content] header
        - artifacts: 合并去重保序
        """
        success_count = sum(1 for s in plan.steps if s.status == "success")
        failed_count = sum(1 for s in plan.steps if s.status == "failed")
        total = len(plan.steps)

        if success_count == total:
            plan.status = "success"
        elif failed_count == total:
            plan.status = "failed"
        else:
            plan.status = "partial"

        # 顺序拼接 outputs，合并 artifacts
        outputs: list[str] = []
        artifacts: list[str] = []
        errors: list[str] = []

        for i, step in enumerate(plan.steps):
            if step.result is None:
                continue

            # header 截断显示前 40 字符
            preview = step.content[:40] + ("..." if len(step.content) > 40 else "")
            outputs.append(f"[Step {i}: {preview}]\n{step.result.output}")

            if step.result.artifacts:
                artifacts.extend(step.result.artifacts)

            if step.result.error:
                errors.append(f"step-{i} ({step.result.provider}): {step.result.error}")

        combined_output = "\n\n".join(outputs)
        # 去重保序
        combined_artifacts: list[str] = list(dict.fromkeys(artifacts))

        # status 映射到 Result（Result 只接受 success/failed/timeout/partial）
        if plan.status == "success":
            result_status = "success"
        elif plan.status == "failed":
            result_status = "failed"
        else:
            result_status = "partial"

        return Result(
            provider="planner",
            status=result_status,
            output=combined_output,
            error="; ".join(errors) if errors else None,
            artifacts=combined_artifacts,
            metadata={
                "plan_id": plan.plan_id,
                "task_id": original_task.task_id,
                "step_count": total,
                "success_count": success_count,
                "failed_count": failed_count,
                "planner": plan.metadata.get("planner", "unknown"),
            },
        )

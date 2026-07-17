# AI Hub — Plan Executor
# V0.9.0: 顺序执行 Plan 中的 Step，聚合结果
#
# 通过组合持有 Router（不继承），对每个 Step 调 router.execute(sub_task)。
# ScoreRouter 的评分、Health 过滤、Quota 管理全部复用。
#
# ADR-0013: V0.9.0 只做顺序执行 + 简单聚合。DAG/并行留 V0.10+。
#
# 聚合规则（V0.9.1 分层 metadata，ADR-0014；V0.9.3 加 schema_version，ADR-0016）：
#   - 全 success → success
#   - 全 failed → failed
#   - 混合 → partial
#   - outputs 顺序拼接（带 step header），artifacts 合并去重
#   - metadata 分层：顶层 plan_id/task_id + schema_version；plan.{status,steps,success,failed}；runtime.{planner,router}
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

    def __init__(
        self,
        router: Router,
        planner: Optional[Planner] = None,
        plan_store: Optional[PlanStore] = None,
    ):
        """
        Args:
            router: Router 实例（与 Planner 共享）
            planner: Planner 实例（默认 RuleBasedPlanner）
            plan_store: PlanStore 实例（V0.9.3 可选，传入后执行完自动 save）
        """
        self.router = router
        self.planner = planner or RuleBasedPlanner()
        self.plan_store = plan_store
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
            step.execution_result = result
            step.status = "success" if result.is_success else "failed"

        # V0.9.3: 执行完后持久化到 plan_store（如果有）
        if self.plan_store is not None:
            self.plan_store.save(plan)

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
            if step.execution_result is None:
                continue

            # header 截断显示前 40 字符
            preview = step.content[:40] + ("..." if len(step.content) > 40 else "")
            outputs.append(f"[Step {i}: {preview}]\n{step.execution_result.output}")

            if step.execution_result.artifacts:
                artifacts.extend(step.execution_result.artifacts)

            if step.execution_result.error:
                errors.append(f"step-{i} ({step.execution_result.provider}): {step.execution_result.error}")

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
                # 顶层稳定标识：plan_id / task_id（ADR-0014 冻结）
                "plan_id": plan.plan_id,
                "task_id": original_task.task_id,
                # plan 子键：计划统计（explain-plan / Dashboard 直接消费）
                "plan": {
                    "status": plan.status,
                    "steps": total,
                    "success": success_count,
                    "failed": failed_count,
                },
                # runtime 子键：执行态信息（V0.10+ 扩展 latency/token/cost/retry）
                "runtime": {
                    "planner": type(self.planner).__name__,
                    "router": type(self.router).__name__,
                },
                # schema_version: V0.9.3 引入（ADR-0016），作为元数据管理字段
                # 允许在顶层（类比 HTTP Content-Type），不破坏 ADR-0014 业务字段冻结
                "schema_version": "1",
            },
        )

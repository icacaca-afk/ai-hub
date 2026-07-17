# AI Hub — Plan Executor
# V0.9.0: 顺序执行 Plan 中的 Step，聚合结果
#
# 通过组合持有 Router（不继承），对每个 Step 调 router.execute(sub_task)。
# ScoreRouter 的评分、Health 过滤、Quota 管理全部复用。
#
# ADR-0013: V0.9.0 只做顺序执行 + 简单聚合。DAG/并行留 V0.10+。
# ADR-0017: V0.9.4 集成 EventBus，关键节点 emit 事件。
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

import time
from typing import Any, Optional

from core.result import Result
from core.task import Task
from planner.base import Planner
from planner.event_bus import EventBus
from planner.execution_event import ExecutionEvent
from planner.execution_metrics import ExecutionMetrics
from planner.plan import Plan
from planner.plan_store import PlanStore
from planner.rule_based_planner import RuleBasedPlanner
from router.router import Router


class PlanExecutor:
    """Plan 执行器。

    组合 Router + Planner + EventBus + PlanStore，把复合 Task 分解后逐步执行并聚合。

    V0.9.0 范围：
        - 顺序执行（不消费 depends_on，不做拓扑排序）
        - 简单聚合（顺序拼接 outputs，合并 artifacts）
        - 不做并行、不做 LLM 总结

    V0.9.3 范围：
        - plan_store 可选参数（执行完后自动 save）

    V0.9.4 范围（ADR-0017）：
        - event_bus 可选参数（执行时关键节点 emit ExecutionEvent）
        - EventBus 缺省时静默跳过（不报错，老 consumer 兼容）

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
        event_bus: Optional[EventBus] = None,
    ):
        """
        Args:
            router: Router 实例（与 Planner 共享）
            planner: Planner 实例（默认 RuleBasedPlanner）
            plan_store: PlanStore 实例（V0.9.3 可选，传入后执行完自动 save）
            event_bus: EventBus 实例（V0.9.4 可选，传入后执行时 emit 事件）
        """
        self.router = router
        self.planner = planner or RuleBasedPlanner()
        self.plan_store = plan_store
        self.event_bus = event_bus
        self.last_plan: Optional[Plan] = None

    def execute(self, task: Task) -> Result:
        """分解 + 顺序执行 + 聚合。

        Args:
            task: 原始复合 Task

        Returns:
            聚合后的 Result（provider="planner"）
        """
        # V0.9.4: emit plan_started（Single Source of Execution Truth）
        self._emit_event("plan_started", plan_id=None, step_id=None, data={"task_id": task.task_id})

        plan = self.planner.decompose(task)
        plan.status = "running"
        self.last_plan = plan

        # V0.9.4: emit planner_started
        self._emit_event("planner_started", plan_id=plan.plan_id, data={"planner": type(self.planner).__name__})

        # V0.9.4: emit planner_finished
        self._emit_event(
            "planner_finished",
            plan_id=plan.plan_id,
            data={"step_count": len(plan.steps)},
        )

        for i, step in enumerate(plan.steps):
            step.status = "running"
            sub_task = Task(
                content=step.content,
                capabilities=step.capabilities,
                context={**task.context, **step.context},
            )

            # V0.9.4: emit step_started
            self._emit_event(
                "step_started",
                plan_id=plan.plan_id,
                step_id=step.step_id,
                data={"index": i, "content_preview": step.content[:40]},
            )

            # V0.9.4: emit provider_selected（ChatGPT 建议：路由决策可观察）
            # 注：V0.9.4 简化处理：emit provider_selected 携带 provider=type(self.router).__name__
            #     实际选中的 provider 来自 result.provider（execute 后才能确定）
            self._emit_event(
                "provider_selected",
                plan_id=plan.plan_id,
                step_id=step.step_id,
                provider=type(self.router).__name__,
                data={"router": type(self.router).__name__},
            )

            # V0.9.4: 计时 provider latency（ChatGPT 建议 D4：仅 Provider latency 显式记录）
            provider_start = time.perf_counter()
            result = self.router.execute(sub_task)
            provider_latency_ms = int((time.perf_counter() - provider_start) * 1000)

            step.execution_result = result
            step.status = "success" if result.is_success else "failed"

            # V0.9.4: emit provider_finished（携带 latency_ms）
            self._emit_event(
                "provider_finished",
                plan_id=plan.plan_id,
                step_id=step.step_id,
                provider=result.provider,
                latency_ms=provider_latency_ms,
                data={"status": result.status},
            )

            # V0.9.4: 填 step.execution_metrics（仅 latency_ms，token/cost 留 V0.9.5+）
            step.execution_metrics = ExecutionMetrics(latency_ms=provider_latency_ms)

            # V0.9.4: emit step_finished
            self._emit_event(
                "step_finished",
                plan_id=plan.plan_id,
                step_id=step.step_id,
                data={"status": step.status, "latency_ms": provider_latency_ms},
            )

        # V0.9.3: 执行完后持久化到 plan_store（如果有）
        if self.plan_store is not None:
            self.plan_store.save(plan)

        aggregated = self._aggregate(plan, task)

        # V0.9.4: emit plan_finished（在 save 后 / aggregate 后）
        self._emit_event(
            "plan_finished",
            plan_id=plan.plan_id,
            data={
                "status": aggregated.status,
                "steps": len(plan.steps),
                "success": aggregated.metadata["plan"]["success"],
                "failed": aggregated.metadata["plan"]["failed"],
            },
        )

        return aggregated

    def _emit_event(
        self,
        event_type: str,
        plan_id: Optional[str] = None,
        step_id: Optional[str] = None,
        provider: Optional[str] = None,
        latency_ms: Optional[int] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """V0.9.4: emit ExecutionEvent 到 EventBus（如果有）。

        event_bus=None 时静默跳过（向后兼容）。
        """
        if self.event_bus is None:
            return
        event = ExecutionEvent(
            type=event_type,
            plan_id=plan_id or "unknown",
            step_id=step_id,
            provider=provider,
            latency_ms=latency_ms,
            data=data or {},
        )
        self.event_bus.emit(event)

    def _aggregate(self, plan: Plan, original_task: Task) -> Result:
        """聚合所有 Step 的结果。

        - status: 全 success→success / 全 failed→failed / 混合→partial
        - output: 顺序拼接，每段带 [Step i: content] header
        - artifacts: 合并去重保序
        - V0.9.4: 填 plan.aggregate_metrics
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

        # V0.9.4: 聚合 Plan metrics
        plan.aggregate_metrics = ExecutionMetrics()
        for s in plan.steps:
            if s.execution_metrics is not None:
                plan.aggregate_metrics.add(s.execution_metrics)

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
                # V0.9.4 (ADR-0017): aggregate_metrics（Plan 层聚合 metrics）
                # 老 consumer 缺字段静默忽略（Postel's Law）
                "aggregate_metrics": plan.aggregate_metrics.to_dict(),
                # schema_version: V0.9.3 引入（ADR-0016），V0.9.4 维持 "1"（ChatGPT 强建议：不升级）
                "schema_version": "1",
            },
        )

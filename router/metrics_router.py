# AI Hub — Metrics-aware Router
# V0.9.6: 在 execute() 中额外提取 server_metrics（ADR-0019）
# V1.0.1: @deprecated — 由 ExecutionPipeline + MetricsStage 替代（ADR-0021）
#
# 继承 ScoreRouter，覆盖 execute()（不改 route()）。
# execute() 复制 Router.execute() 的主链路，仅在 bridge.run 后插入 MetricsExtractor。
#
# ChatGPT 审核约束 (ADR-0019 原则 F):
#   - MetricsRouter MUST NOT influence provider selection or routing decisions.
#   - MetricsRouter is a temporary compatibility layer.
#   - V2.0 退出路径：BridgeResult raw extension（直接在 BridgeResult 上携带结构化 metrics）。
#
# V1.0.1 退出路径（ADR-0021 9.95/10 FINAL APPROVED）:
#   - 选中 ExecutionPipeline as Decorator / Middleware 路径
#   - MetricsStage 取代 MetricsRouter.execute() 装饰
#   - MetricsRouter 保留向后兼容（V1.0.3 删除）
#
#   新代码应该用：
#       from planner.pipeline import default_pipeline
#       pipeline = default_pipeline(score_router, quota=quota)
#       result = pipeline.run(task)
#
# API Stability: Deprecated（V1.0.3 删除）

from __future__ import annotations

import warnings

from core.result import Result
from core.task import Task
from planner.metrics.extractors import MetricsExtractor
from router.score_router import ScoreRouter


class MetricsRouter(ScoreRouter):
    """ScoreRouter 子类：在 execute() 中额外提取 server_metrics。

    ⚠️ DEPRECATED since V1.0.1 (ADR-0021). Will be removed in V1.0.3.

    route() 完全继承 ScoreRouter，不影响路由决策。
    execute() 在 bridge.run() 之后调用 MetricsExtractor.extract()，
    把返回的 server_metrics dict 放进 Result.metadata["server_metrics"]。

    提取失败 / provider 不支持 → server_metrics = {}（不影响主链路）。

    V1.0.1 替代方案（推荐）：
        from planner.pipeline import default_pipeline
        from router.score_router import ScoreRouter
        pipeline = default_pipeline(ScoreRouter(...), quota=quota)
        result = pipeline.run(task)
        # MetricsStage 自动提取 server_metrics

    API Stability: Deprecated
    """

    def execute(self, task: Task) -> Result:
        """路由并执行任务，附带 server_metrics。

        ⚠️ DEPRECATED since V1.0.1 (ADR-0021). Use ExecutionPipeline + MetricsStage instead.

        链路：route → select_bridge → bridge.run → extract metrics → Result
        """
        warnings.warn(
            "MetricsRouter.execute() is deprecated since V1.0.1 (ADR-0021). "
            "Use ExecutionPipeline + MetricsStage instead: "
            "from planner.pipeline import default_pipeline; "
            "pipeline = default_pipeline(router, quota=quota); "
            "result = pipeline.run(task). "
            "Will be removed in V1.0.3.",
            DeprecationWarning,
            stacklevel=2,
        )
        provider = self.route(task)

        if provider is None:
            return Result(
                provider="none",
                status="failed",
                output="",
                error=f"No available provider for capabilities: {task.capabilities}",
                metadata={"capabilities": task.capabilities, "task_id": task.task_id},
            )

        # 执行前检查配额（防御性，route 已过滤）
        if self.quota and self.quota.exhausted(provider.name):
            return Result(
                provider=provider.name,
                status="failed",
                output="",
                error=f"Quota exhausted for {provider.name}",
                metadata={
                    "capabilities": task.capabilities,
                    "task_id": task.task_id,
                    "fallback_reason": "quota_exhausted",
                },
            )

        bridge = provider.select_bridge(task)
        br = bridge.run(task)

        # V0.9.6 新增：从 br.raw 提取 server_metrics
        # 失败/无数据返回 {}（不影响主链路）
        server_metrics = MetricsExtractor.extract(provider.name, bridge, br)

        # 成功时扣减配额
        if br.success and self.quota:
            self.quota.ensure(
                provider.name,
                provider.metadata.quota_total,
                provider.metadata.quota_type,
            )
            self.quota.consume(provider.name, task_id=task.task_id)

        return Result(
            provider=provider.name,
            status="success" if br.success else "failed",
            output=br.output,
            error=br.error,
            artifacts=br.artifacts,
            metadata={
                "duration_ms": br.duration_ms,
                "capabilities": task.capabilities,
                "task_id": task.task_id,
                "bridge": type(bridge).__name__,
                "quota_remaining": provider.quota_left(),
                "server_metrics": server_metrics,
            },
        )

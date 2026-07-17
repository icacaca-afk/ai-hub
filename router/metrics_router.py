# AI Hub — Metrics-aware Router
# V0.9.6: 在 execute() 中额外提取 server_metrics（ADR-0019）
#
# 继承 ScoreRouter，覆盖 execute()（不改 route()）。
# execute() 复制 Router.execute() 的主链路，仅在 bridge.run 后插入 MetricsExtractor。
#
# ChatGPT 审核约束 (ADR-0019 原则 F):
#   - MetricsRouter MUST NOT influence provider selection or routing decisions.
#   - MetricsRouter is a temporary compatibility layer.
#   - V2.0 退出路径：BridgeResult raw extension（直接在 BridgeResult 上携带结构化 metrics）。
#
# API Stability: Experimental

from __future__ import annotations

from core.result import Result
from core.task import Task
from planner.metrics.extractors import MetricsExtractor
from router.score_router import ScoreRouter


class MetricsRouter(ScoreRouter):
    """ScoreRouter 子类：在 execute() 中额外提取 server_metrics。

    route() 完全继承 ScoreRouter，不影响路由决策。
    execute() 在 bridge.run() 之后调用 MetricsExtractor.extract()，
    把返回的 server_metrics dict 放进 Result.metadata["server_metrics"]。

    提取失败 / provider 不支持 → server_metrics = {}（不影响主链路）。

    API Stability: Experimental
    """

    def execute(self, task: Task) -> Result:
        """路由并执行任务，附带 server_metrics。

        链路：route → select_bridge → bridge.run → extract metrics → Result
        """
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

# AI Hub — Execution Pipeline
# V1.0.1: Decorator / Middleware pattern for execution chain
#
# 取代 V0.9.6 MetricsRouter 子类层级，让 Router 重新变瘦。
# 所有执行期关注点（metrics / health / future retry / future checkpoint）
# 走 ExecutionPipeline 装饰器链。
#
# ADR-0021 V1.0.1: ExecutionPipeline as Decorator / Middleware
# ChatGPT 外部审核：9.95/10 FINAL APPROVED
# 采纳 3 项调整：
#   1. Q3 短路语义：ctx.result is not None -> 显式 ctx.stop: bool 字段
#   2. Decision 3 RouteStage 职责：只选 Provider/Bridge，不执行 bridge.run
#   3. Decision 8 Version Evolution 表：V0.9 -> V1.0 -> V2.0 MetricsRouter Migration
#
# 关键不变量（继承自 Runtime Contract）：
#   - ExecutionContext 不可变（with_xxx 每次返回新对象）
#   - Stage 不修改 ExecutionEvent（Runtime Contract 原则 B）
#   - Stage 不接触 SQLite / EventBus（除非显式订阅）
#   - Pipeline 失败必须返回 Result（不抛异常）
#   - Router.execute() 保留向后兼容（Pipeline 不用）
#   - MetricsRouter 标记 @deprecated（V1.0.3 删除）
#
# API Stability: Experimental
# V1.0.2+ 评估：Stage SHOULD be Side-Effect Minimal（V1.0+ 评估）

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

from core.bridge import BridgeResult
from core.provider import Provider
from core.result import Result
from core.task import Task
from router.router import Router

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# ExecutionContext — 不可变上下文
# ─────────────────────────────────────────────────────────────

@dataclass
class ExecutionContext:
    """Pipeline 透传的不可变上下文。

    Attributes:
        task: 当前 Task
        provider: route() 选中的 Provider（None 表示 routing 失败或尚未选）
        bridge: select_bridge() 选中的 Bridge 实例（None 表示尚未选）
        bridge_result: bridge.run() 返回的 BridgeResult（None 表示尚未执行）
        result: 最终或中间 Result（短路时由 Stage 设置）
        stop: 短路标志。True 时 Pipeline 跳过剩余 Stage，直接返回 ctx.result。
             （ChatGPT Q3 调整：从 ctx.result is not None 演进为显式 stop 字段）

    API Stability: Experimental
    """

    task: Task
    provider: Optional[Provider] = None
    bridge: Any = None  # Bridge 实例（RouteStage 选定，不调 run）
    bridge_result: Optional[BridgeResult] = None
    result: Optional[Result] = None
    stop: bool = False

    def with_provider(
        self, provider: Optional[Provider], bridge: Any = None
    ) -> "ExecutionContext":
        """返回新 context，更新 provider（可选更新 bridge）。

        Args:
            provider: 新的 Provider
            bridge: 新的 Bridge（None 表示保持当前 bridge）
        """
        return ExecutionContext(
            task=self.task,
            provider=provider,
            bridge=bridge if bridge is not None else self.bridge,
            bridge_result=self.bridge_result,
            result=self.result,
            stop=self.stop,
        )

    def with_bridge_result(self, br: BridgeResult) -> "ExecutionContext":
        """返回新 context，更新 bridge_result。"""
        return ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge=self.bridge,
            bridge_result=br,
            result=self.result,
            stop=self.stop,
        )

    def with_result(self, result: Result, stop: bool = True) -> "ExecutionContext":
        """返回新 context，设置 result 并标记 stop（默认 True）。

        Args:
            result: 最终或中间 Result
            stop: 是否短路（默认 True：调用 with_result 通常意味着终止）
        """
        return ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge=self.bridge,
            bridge_result=self.bridge_result,
            result=result,
            stop=stop,
        )

    def with_stop(self) -> "ExecutionContext":
        """返回新 context，显式设置 stop=True（不修改其他字段）。"""
        return ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge=self.bridge,
            bridge_result=self.bridge_result,
            result=self.result,
            stop=True,
        )


# ─────────────────────────────────────────────────────────────
# ExecutionStage — Stage 接口（Protocol）
# ─────────────────────────────────────────────────────────────

@runtime_checkable
class ExecutionStage(Protocol):
    """Pipeline Stage 接口（V1.0.1 Protocol）。

    每个 Stage 负责一个关注点：
    - RouteStage（V1.0.1 必选）：选 Provider + Bridge
    - MetricsStage（V1.0.1 必选）：提取 server_metrics
    - RetryStage（V1.0.2）：失败重试
    - CheckpointStage（V1.0.3）：断点续跑
    - ConditionStage（V1.0.4）：条件分支

    Stage 通过修改 context（with_xxx）或短路（ctx.stop = True）介入执行链。
    Stage 不修改 ExecutionEvent（Runtime Contract 原则 B）。

    短路语义（ChatGPT Q3 调整）：
    不要用 `ctx.result is not None` 检测短路。
    用显式 `ctx.stop: bool` 字段。
    原因：未来 RetryStage 可能需要区分 ctx.exception / ctx.retry / ctx.result
    三种状态可能同时存在，ctx.stop 语义更明确。

    API Stability: Experimental
    """

    @property
    def name(self) -> str:
        """Stage 名称（用于日志/调试）。"""
        ...

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """处理 context，返回新 context（不可变）。

        Returns:
            新的 ExecutionContext。短路时设置 ctx.stop = True。
        """
        ...


# ─────────────────────────────────────────────────────────────
# RouteStage — 选 Provider + Bridge（不执行）
# ─────────────────────────────────────────────────────────────

class RouteStage:
    """Pre-bridge Stage：调用 router.route() 选 Provider + Bridge（不执行）。

    ChatGPT Decision 3 调整（采纳）：
    RouteStage 只负责"选择"（Provider + Bridge），不负责"执行"（bridge.run）。
    - Router.route(task) -> ctx.provider
    - provider.select_bridge(task) -> ctx.bridge
    - bridge.run(task) -> 由 ExecutionPipeline._base_execute 负责

    让 Router 只负责 route()，不负责 execute() 装饰。

    API Stability: Experimental
    """

    def __init__(self, router: Router):
        self.router = router
        self._name = "route"

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """调用 router.route() 设置 ctx.provider，再选 ctx.bridge（不执行）。

        路由失败（provider is None）时短路：
        - ctx.result = failed Result
        - ctx.stop = True
        - Pipeline 跳过 base_execute
        """
        provider = self.router.route(ctx.task)
        if provider is None:
            return ctx.with_result(
                Result(
                    provider="none",
                    status="failed",
                    output="",
                    error=f"No available provider for capabilities: {ctx.task.capabilities}",
                    metadata={
                        "capabilities": ctx.task.capabilities,
                        "task_id": ctx.task.task_id,
                    },
                ),
                stop=True,
            ).with_provider(None)

        # ChatGPT 采纳：RouteStage 也选 bridge（不执行），存到 ctx.bridge
        bridge = provider.select_bridge(ctx.task)
        return ctx.with_provider(provider, bridge=bridge)


# ─────────────────────────────────────────────────────────────
# MetricsStage — 提取 server_metrics
# ─────────────────────────────────────────────────────────────

class MetricsStage:
    """Post-bridge Stage：从 BridgeResult 提取 server_metrics。

    取代 MetricsRouter.execute() 中的内联 metrics 提取逻辑。

    关键约束：
    - 提取失败 -> server_metrics = {}（不影响主链路）
    - 不修改 ctx.bridge_result（不可变）
    - 不抛异常
    - 不写回 SQLite / EventBus（Stage SHOULD be Side-Effect Minimal）

    API Stability: Experimental
    """

    def __init__(self, extractor: Any = None):
        # Lazy import 避免循环依赖
        if extractor is None:
            from planner.metrics.extractors import MetricsExtractor
            extractor = MetricsExtractor()
        self.extractor = extractor
        self._name = "metrics"

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """从 ctx.bridge_result 提取 server_metrics 并写入 ctx.result.metadata。

        短路条件：
        - ctx.stop = True（已被前面 Stage 短路）
        - ctx.bridge_result is None（base_execute 失败）
        - ctx.bridge is None（RouteStage 没选 bridge）

        失败处理：
        - MetricsExtractor.extract 抛异常 -> log + server_metrics={}，继续
        """
        if ctx.stop or ctx.bridge_result is None or ctx.bridge is None:
            return ctx  # 不处理

        provider_name = ctx.provider.name if ctx.provider else "unknown"

        try:
            server_metrics = self.extractor.extract(
                provider_name, ctx.bridge, ctx.bridge_result
            )
        except Exception as e:
            # 提取失败不抛异常，log 后继续
            logger.warning(
                "MetricsStage skipped event: provider=%s exception=%s message=%s",
                provider_name, type(e).__name__, str(e),
            )
            server_metrics = {}

        # 构造新 Result（包含 server_metrics）
        # 如果 ctx.result 已有（比如用户手动 set），合并 metadata；否则构造默认
        if ctx.result is not None:
            new_metadata = dict(ctx.result.metadata)
        else:
            new_metadata = {}
        new_metadata["server_metrics"] = server_metrics
        new_result = Result(
            provider=ctx.provider.name if ctx.provider else provider_name,
            status="success" if ctx.bridge_result.success else "failed",
            output=ctx.bridge_result.output,
            error=ctx.bridge_result.error,
            artifacts=list(ctx.bridge_result.artifacts),
            metadata=new_metadata,
        )
        return ctx.with_result(new_result, stop=False)


# ─────────────────────────────────────────────────────────────
# PipelineExecutor — 组装最终 Result
# ─────────────────────────────────────────────────────────────

class PipelineExecutor:
    """Pipeline 内部 helper：组装最终 Result。

    V1.0.1 简化版：直接从 ctx 派生 Result。
    V1.0.2+ 扩展：增加 Result 中间件（post-processing）。

    API Stability: Experimental
    """

    @staticmethod
    def assemble_result(ctx: ExecutionContext) -> Result:
        """从 ctx 组装最终 Result。

        Returns:
            Result：成功 / 失败 / 短路

        关键：
        - 短路（ctx.result is not None）直接返回 ctx.result
        - 正常情况从 ctx.bridge_result 组装
        - 异常情况（base_execute 失败）返回 failed Result
        """
        if ctx.result is not None:
            # 已有 result（短路或 Stage 已组装）
            return ctx.result

        if ctx.bridge_result is None or ctx.provider is None:
            # 不应到达这里，但防御性
            return Result(
                provider=ctx.provider.name if ctx.provider else "unknown",
                status="failed",
                output="",
                error="Pipeline internal error: missing bridge_result",
                metadata={"task_id": ctx.task.task_id},
            )

        br = ctx.bridge_result
        return Result(
            provider=ctx.provider.name,
            status="success" if br.success else "failed",
            output=br.output,
            error=br.error,
            artifacts=br.artifacts,
            metadata={
                "duration_ms": br.duration_ms,
                "capabilities": ctx.task.capabilities,
                "task_id": ctx.task.task_id,
                "bridge": type(ctx.bridge).__name__ if ctx.bridge else "unknown",
                "quota_remaining": ctx.provider.quota_left(),
            },
        )


# ─────────────────────────────────────────────────────────────
# ExecutionPipeline — 主入口
# ─────────────────────────────────────────────────────────────

class ExecutionPipeline:
    """执行管道：Stage 列表 + Router + Base Executor。

    执行流程（V1.0.1）：
        1. Pipeline.run(task) 入口
        2. for stage in pre_bridge_stages: ctx = stage(ctx); if ctx.stop: break
        3. provider / bridge = ctx.provider / ctx.bridge (来自 RouteStage)
        4. br = bridge.run(task)  # Base Execute（仅当 ctx.stop=False 且 bridge 存在）
        5. ctx = ctx.with_bridge_result(br)
        6. for stage in post_bridge_stages: ctx = stage(ctx); if ctx.stop: break
        7. return PipelineExecutor.assemble_result(ctx)

    Stage 注册顺序：
        pre_bridge:  [RouteStage]
        post_bridge: [MetricsStage, HealthStage, ...]（按关注点顺序）

    V1.0.1 默认 pipeline:
        pre_bridge:  [RouteStage()]
        post_bridge: [MetricsStage()]

    V1.0.2+ 增加:
        post_bridge: [MetricsStage(), RetryStage()]
        等

    关键变更（ChatGPT Q3 采纳）：
    - 短路检查：ctx.stop 字段（替代 ctx.result is not None）
    - RouteStage 设置 ctx.bridge（不调 bridge.run）
    - _base_execute 调 ctx.bridge.run()

    API Stability: Experimental
    """

    def __init__(
        self,
        router: Router,
        pre_bridge_stages: Optional[list] = None,
        post_bridge_stages: Optional[list] = None,
        quota: Any = None,
    ):
        self.router = router
        self.pre_bridge_stages = pre_bridge_stages or []
        self.post_bridge_stages = post_bridge_stages or []
        self.quota = quota

    def run(self, task: Task) -> Result:
        """执行 task 经过所有 Stage，返回 Result。"""
        ctx = ExecutionContext(task=task)

        # 1. Pre-bridge stages
        for stage in self.pre_bridge_stages:
            ctx = stage(ctx)
            if ctx.stop:
                return ctx.result if ctx.result else self._error_result(
                    ctx, f"stopped in pre_bridge stage '{stage.name}'"
                )

        # 2. Base execute（bridge.run）
        ctx = self._base_execute(ctx)
        if ctx.stop:
            return ctx.result if ctx.result else self._error_result(
                ctx, "stopped in base_execute"
            )

        # 3. Post-bridge stages
        for stage in self.post_bridge_stages:
            ctx = stage(ctx)
            if ctx.stop:
                # post-bridge Stage 短路，直接用 ctx.result
                if ctx.result is not None:
                    return ctx.result
                # Stage 设 stop 但没设 result -> 防御性
                return self._error_result(
                    ctx, f"post_bridge stage '{stage.name}' stopped without result"
                )

        # 4. 组装 Result
        return PipelineExecutor.assemble_result(ctx)

    def _base_execute(self, ctx: ExecutionContext) -> ExecutionContext:
        """薄薄一层：bridge.run + quota 管理。

        这一层取代 Router.execute() 的主链路。
        不再被子类覆盖，所有装饰逻辑在 Stage 里。
        """
        if ctx.bridge is None or ctx.provider is None:
            # 不应到达这里（RouteStage 已经选好）
            # 防御性
            return ctx.with_result(
                Result(
                    provider=ctx.provider.name if ctx.provider else "unknown",
                    status="failed",
                    output="",
                    error="Pipeline internal error: no bridge selected",
                    metadata={"task_id": ctx.task.task_id},
                ),
                stop=True,
            )

        # 执行前检查配额
        if self.quota and self.quota.exhausted(ctx.provider.name):
            return ctx.with_result(
                Result(
                    provider=ctx.provider.name,
                    status="failed",
                    output="",
                    error=f"Quota exhausted for {ctx.provider.name}",
                    metadata={
                        "capabilities": ctx.task.capabilities,
                        "task_id": ctx.task.task_id,
                        "fallback_reason": "quota_exhausted",
                    },
                ),
                stop=True,
            )

        br = ctx.bridge.run(ctx.task)

        # 成功时扣减配额
        if br.success and self.quota:
            self.quota.ensure(
                ctx.provider.name,
                ctx.provider.metadata.quota_total,
                ctx.provider.metadata.quota_type,
            )
            self.quota.consume(ctx.provider.name, task_id=ctx.task.task_id)

        return ctx.with_bridge_result(br)

    def _error_result(self, ctx: ExecutionContext, message: str) -> Result:
        """构造防御性 failed Result（不应到达）。"""
        return Result(
            provider=ctx.provider.name if ctx.provider else "unknown",
            status="failed",
            output="",
            error=message,
            metadata={"task_id": ctx.task.task_id},
        )


# ─────────────────────────────────────────────────────────────
# default_pipeline — 工厂函数
# ─────────────────────────────────────────────────────────────

def default_pipeline(
    router: Router,
    quota: Any = None,
    include_metrics: bool = True,
) -> ExecutionPipeline:
    """构造 V1.0.1 默认 Pipeline。

    默认 Stages:
        pre_bridge:  [RouteStage(router)]
        post_bridge: [MetricsStage()]  (if include_metrics)

    Args:
        router: Router 实例（通常是 ScoreRouter）
        quota: QuotaManager（可选）
        include_metrics: 是否包含 MetricsStage（默认 True）

    Returns:
        ExecutionPipeline 实例

    API Stability: Experimental
    """
    pre_bridge = [RouteStage(router)]
    post_bridge = []
    if include_metrics:
        post_bridge.append(MetricsStage())
    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
        quota=quota,
    )

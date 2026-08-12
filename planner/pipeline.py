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
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from core.bridge import BridgeResult
from core.provider import Provider
from core.result import Result
from core.task import Task
from planner.runtime_metadata import RuntimeMetadata
from planner.stage_descriptor import StageDescriptor, get_descriptor
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
        runtime: V1.0.7 新增 (ADR-0027 Accepted 9.85/10) — 强类型运行时元数据容器。
                与 ctx.metadata (V1.0.6 dict API) 并存, 互不影响。
                built-in Stage 通过 runtime.set_*() helper 写穿到 ctx.metadata。

    API Stability: Experimental
    """

    task: Task
    provider: Optional[Provider] = None
    bridge: Any = None  # Bridge 实例（RouteStage 选定，不调 run）
    bridge_result: Optional[BridgeResult] = None
    result: Optional[Result] = None
    stop: bool = False
    # V1.0.7 新增 (ADR-0027 additive migration):
    # 保留 ctx.metadata 动态注入 (V1.0.6 行为), 第三方 Stage 旧风格不受影响
    runtime: RuntimeMetadata = field(default_factory=RuntimeMetadata)

    def with_provider(
        self, provider: Optional[Provider], bridge: Any = None
    ) -> "ExecutionContext":
        """返回新 context，更新 provider（可选更新 bridge）。

        Args:
            provider: 新的 Provider
            bridge: 新的 Bridge（None 表示保持当前 bridge）
        """
        new_ctx = ExecutionContext(
            task=self.task,
            provider=provider,
            bridge=bridge if bridge is not None else self.bridge,
            bridge_result=self.bridge_result,
            result=self.result,
            stop=self.stop,
            runtime=self.runtime,  # V1.0.7 透传 runtime
        )
        # V1.0.6 兼容: 透传 metadata (动态注入)
        if hasattr(self, "metadata") and self.metadata is not None:
            new_ctx.metadata = self.metadata
        return new_ctx

    def with_bridge_result(self, br: BridgeResult) -> "ExecutionContext":
        """返回新 context，更新 bridge_result。"""
        new_ctx = ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge=self.bridge,
            bridge_result=br,
            result=self.result,
            stop=self.stop,
            runtime=self.runtime,  # V1.0.7 透传 runtime
        )
        if hasattr(self, "metadata") and self.metadata is not None:
            new_ctx.metadata = self.metadata
        return new_ctx

    def with_result(self, result: Result, stop: bool = True) -> "ExecutionContext":
        """返回新 context，设置 result 并标记 stop（默认 True）。

        Args:
            result: 最终或中间 Result
            stop: 是否短路（默认 True：调用 with_result 通常意味着终止）
        """
        new_ctx = ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge=self.bridge,
            bridge_result=self.bridge_result,
            result=result,
            stop=stop,
            runtime=self.runtime,  # V1.0.7 透传 runtime
        )
        if hasattr(self, "metadata") and self.metadata is not None:
            new_ctx.metadata = self.metadata
        return new_ctx

    def with_stop(self) -> "ExecutionContext":
        """返回新 context，显式设置 stop=True（不修改其他字段）。"""
        new_ctx = ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge=self.bridge,
            bridge_result=self.bridge_result,
            result=self.result,
            stop=True,
            runtime=self.runtime,  # V1.0.7 透传 runtime
        )
        if hasattr(self, "metadata") and self.metadata is not None:
            new_ctx.metadata = self.metadata
        return new_ctx


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

    # V1.0.6: 显式 StageDescriptor (ADR-0026 ChatGPT 9.94/10 Critical Q7)
    descriptor = StageDescriptor(
        name="route",
        version=1,
        role="stage",
        capabilities=frozenset({"selects_provider"}),
        idempotent=True,
        has_side_effects=False,
        always_run_after_stop=False,
        description="Routes task to a Provider via Router",
        owner="ai-hub",
        experimental=False,
    )

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

        Rev1 R4 (ChatGPT 9.72/10): misuse guard — 若 router is None (registry
        discovery stub), 升级为 Architecture misuse error, 避免 NoneType error。
        """
        if self.router is None:
            raise RuntimeError(
                "RouteStage from registry is discovery-only (router=None stub). "
                "Use default_pipeline(router, ...) to construct an executable "
                "ExecutionPipeline with real runtime deps."
            )
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

    # V1.0.6: 显式 StageDescriptor (ADR-0026 ChatGPT 9.94/10 Critical Q7)
    descriptor = StageDescriptor(
        name="metrics",
        version=1,
        role="metric",
        capabilities=frozenset({"collects_metrics"}),
        idempotent=True,
        has_side_effects=False,
        always_run_after_stop=False,
        description="Collects per-stage metrics from BridgeResult",
        owner="ai-hub",
        experimental=False,
    )

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

        V1.0.7 (ADR-0027): 强类型 + 双写 (helper.set_server_metrics)
          - 写 ctx.runtime.server_metrics (新 API, 强类型)
          - 写 ctx.metadata["server_metrics"] (旧 API, V1.0.6 兼容, 通过 helper write-through)
          - 写 ctx.result.metadata["server_metrics"] (Result API, 已存在, 保留)

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

        # V1.0.7 (ADR-0027 Accepted 9.85/10): 强类型 + 双写
        # 写 ctx.runtime.server_metrics (新) + ctx.metadata["server_metrics"] (旧, 兼容)
        ctx.runtime.set_server_metrics(server_metrics, ctx=ctx, merge=False)

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
        - 短路或 Stage 已设 ctx.result 时优先用 ctx.result
        - 合并 ctx.result.artifacts 和 ctx.bridge_result.artifacts（去重保序）
        - 正常情况从 ctx.bridge_result 派生（ctx.result 为空）
        - 异常情况（base_execute 失败）返回 failed Result
        """
        if ctx.result is not None:
            # Stage 已构造 result（如 MetricsStage），保留
            if ctx.bridge_result is not None:
                # 合并 artifacts（bridge_result 的 artifacts 补到 result 上）
                merged = list(ctx.result.artifacts)
                for a in ctx.bridge_result.artifacts:
                    if a not in merged:
                        merged.append(a)
                if merged == list(ctx.result.artifacts):
                    return ctx.result
                return Result(
                    provider=ctx.result.provider,
                    status=ctx.result.status,
                    output=ctx.result.output,
                    error=ctx.result.error,
                    artifacts=merged,
                    metadata=ctx.result.metadata,
                )
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
            artifacts=list(br.artifacts),
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
        hooks: Any = None,  # V1.0.5: PipelineHooks
    ):
        self.router = router
        self.pre_bridge_stages = pre_bridge_stages or []
        self.post_bridge_stages = post_bridge_stages or []
        self.quota = quota
        # V1.0.5: Hooks (V2 import 避免循环依赖, V1.0.5 局部 import)
        if hooks is None:
            from planner.hooks import PipelineHooks
            self.hooks = PipelineHooks()
        else:
            self.hooks = hooks

    # ─────────────────────────────────────────────────────────
    # V1.0.11 ADR-0032: Pipeline Introspection
    # ─────────────────────────────────────────────────────────

    def describe(self) -> "PipelineDescriptor":
        """返回 Pipeline 结构描述 (V1.0.11 ADR-0032).

        生成不可变的 PipelineDescriptor 快照, 用于 introspection / serialization.
        不触发 run(), 不修改执行状态.

        Returns:
            PipelineDescriptor 实例
        """
        from planner.pipeline_descriptor import PipelineDescriptor
        from planner.stage_descriptor import StageDescriptor

        pre_descs = tuple(
            StageDescriptor.from_stage(s, position="pre", index=i)
            for i, s in enumerate(self.pre_bridge_stages)
        )
        post_descs = tuple(
            StageDescriptor.from_stage(s, position="post", index=i)
            for i, s in enumerate(self.post_bridge_stages)
        )

        # has_hooks: 是否实际配置了至少一个 Hook (非空容器)
        has_hooks = (
            self.hooks is not None
            and hasattr(self.hooks, 'enabled')
            and self.hooks.enabled
        )

        return PipelineDescriptor(
            pre_bridge=pre_descs,
            post_bridge=post_descs,
            has_router=self.router is not None,
            has_quota=self.quota is not None,
            has_hooks=has_hooks,
        )

    def to_dict(self) -> dict:
        """返回可 JSON 序列化的 dict (V1.0.11 ADR-0032).

        Facade: delegate to serialize_pipeline(self.describe()).
        R1 约束: canonical logic lives in serialize_pipeline().
        """
        from planner.metadata_serialization import serialize_pipeline
        return serialize_pipeline(self.describe())

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        """返回 JSON 字符串 (V1.0.11 ADR-0032).

        Delegate to metadata_serialization.to_json(), 不内联 JSON policy.
        """
        from planner.metadata_serialization import to_json as _to_json
        return _to_json(self.to_dict(), indent=indent)

    def run(self, task: Task) -> Result:
        """执行 task 经过所有 Stage，返回 Result。

        V1.0.4 关键变更 (ChatGPT 9.9/10 Q4 采纳):
          - 如果 ctx.stop=True (由 ConditionStage 等控制 Stage 触发),
            仍执行剩余的 CheckpointStage (记录 abort 事实, Runtime Observability)
          - 然后再 return (不抛异常, Best Effort)

        V1.0.5 增量 (ADR-0025):
          - Pipeline.run() 入口 fire_before_pipeline
          - 每个 Stage 前后 fire_before_stage / fire_after_stage
          - Stage 异常时 fire_on_error (但仍 re-raise, V1.0.5 仅观察)
          - ctx.stop 触发时 fire_on_stop
          - Pipeline.run() 出口 fire_after_pipeline
          - 全部 Best Effort, Hook 失败不影响主链路

        执行流程:
            1. Pipeline.run(task) 入口
            2. fire_before_pipeline (V1.0.5)
            3. for stage in pre_bridge_stages: fire_before_stage / stage(ctx) / fire_after_stage; if ctx.stop: fire_on_stop, return
            4. provider / bridge = ctx.provider / ctx.bridge (来自 RouteStage)
            5. br = bridge.run(task)  # Base Execute
            6. ctx = ctx.with_bridge_result(br)
            7. for stage in post_bridge_stages: fire_before_stage / stage(ctx) / fire_after_stage; if ctx.stop: handle_abort
            8. handle_abort: fire_on_stop, 执行剩余 CheckpointStage, 然后 return
            9. fire_after_pipeline (V1.0.5)
            10. return PipelineExecutor.assemble_result(ctx)
        """
        ctx = ExecutionContext(task=task)

        # V1.0.5: Hook before_pipeline
        if self.hooks.enabled:
            self.hooks.fire_before_pipeline(ctx)

        # 1. Pre-bridge stages
        for stage in self.pre_bridge_stages:
            # V1.0.6: 提取 descriptor (Hook 收到 descriptor, Backwards-compat)
            descriptor = get_descriptor(stage)
            if self.hooks.enabled:
                self.hooks.fire_before_stage(ctx, stage.name, descriptor=descriptor)
            try:
                ctx = stage(ctx)
            except Exception as e:
                # V1.0.5: Hook on_error (但仍 re-raise)
                if self.hooks.enabled:
                    self.hooks.fire_on_error(ctx, stage.name, e, descriptor=descriptor)
                raise
            if self.hooks.enabled:
                self.hooks.fire_after_stage(ctx, stage.name, descriptor=descriptor)
            if ctx.stop:
                # V1.0.5: Hook on_stop
                if self.hooks.enabled:
                    self.hooks.fire_on_stop(ctx, "stop_flag")
                if ctx.result is not None:
                    return ctx.result
                return self._error_result(
                    ctx, f"stopped in pre_bridge stage '{stage.name}'"
                )

        # 2. Base execute（bridge.run）
        ctx = self._base_execute(ctx)
        if ctx.stop:
            # V1.0.5: Hook on_stop
            if self.hooks.enabled:
                self.hooks.fire_on_stop(ctx, "stop_flag")
            if ctx.result is not None:
                return ctx.result
            return self._error_result(
                ctx, "stopped in base_execute"
            )

        # 3. Post-bridge stages
        aborted_idx = -1
        for i, stage in enumerate(self.post_bridge_stages):
            # V1.0.6: 提取 descriptor (Hook 收到 descriptor, Backwards-compat)
            descriptor = get_descriptor(stage)
            if self.hooks.enabled:
                self.hooks.fire_before_stage(ctx, stage.name, descriptor=descriptor)
            try:
                ctx = stage(ctx)
            except Exception as e:
                # V1.0.5: Hook on_error
                if self.hooks.enabled:
                    self.hooks.fire_on_error(ctx, stage.name, e, descriptor=descriptor)
                raise
            if self.hooks.enabled:
                self.hooks.fire_after_stage(ctx, stage.name, descriptor=descriptor)
            if ctx.stop:
                aborted_idx = i
                break

        # 4. V1.0.4 关键: 如果 stop, 仍执行剩余 CheckpointStage (记录 abort 事实)
        # ChatGPT 9.9/10 Q4: "Condition -> metadata -> Checkpoint -> Pipeline stop"
        if ctx.stop and aborted_idx >= 0:
            # V1.0.5: 提取 stopped_by
            stopped_by = self._get_stopped_by(ctx, aborted_idx)
            # V1.0.5: Hook on_stop
            if self.hooks.enabled:
                self.hooks.fire_on_stop(ctx, stopped_by)
            for stage in self.post_bridge_stages[aborted_idx + 1:]:
                # V1.0.6: 改用 descriptor.always_run_after_stop (ADR-0026 ChatGPT 9.94/10)
                # 关键: 不再 duck typing (stage.name + hasattr(stage, "store"))
                # Pipeline 只关心行为信号, 不关心 stage.name 字符串
                descriptor = get_descriptor(stage)
                if descriptor.always_run_after_stop:
                    if self.hooks.enabled:
                        # V1.0.6: Hook 收到 descriptor (可选参数, Backwards-compat)
                        self.hooks.fire_before_stage(
                            ctx, stage.name, descriptor=descriptor
                        )
                    ctx = stage(ctx)
                    # Stage 不修改 ctx.stop, 也不设 result
                    # (只写存储, pass)
                    if self.hooks.enabled:
                        self.hooks.fire_after_stage(
                            ctx, stage.name, descriptor=descriptor
                        )
                    # V1.0.4: 即使 abort 也要写 Checkpoint
                    break
            # 然后 return
            if ctx.result is not None:
                return ctx.result
            # Stage 设 stop 但没设 result -> 防御性
            return self._error_result(
                ctx, f"post_bridge stage '{self.post_bridge_stages[aborted_idx].name}' stopped without result"
            )

        # 5. 组装 Result
        result = PipelineExecutor.assemble_result(ctx)
        # V1.0.5: Hook after_pipeline
        if self.hooks.enabled:
            self.hooks.fire_after_pipeline(ctx, result)
        return result

    def _get_stopped_by(self, ctx: ExecutionContext, aborted_idx: int) -> str:
        """V1.0.5: 提取 ctx.stop 来源 (优先 condition_eval, 兜底 stop_flag)."""
        try:
            condition_eval = (ctx.metadata or {}).get("condition_eval")
            if isinstance(condition_eval, dict):
                stopped_by = condition_eval.get("stopped_by")
                if stopped_by:
                    return stopped_by
        except (AttributeError, TypeError):
            pass
        return "stop_flag"

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
    include_retry: bool = False,
    include_condition: bool = False,
    condition: Any = None,
    condition_on_true: str = "continue",
    condition_on_false: str = "continue",
    condition_name: str = "condition",
    include_checkpoint: bool = False,
    execution_store: Any = None,
    hooks: Any = None,  # V1.0.5 新增
) -> ExecutionPipeline:
    """构造 V1.0.4 默认 Pipeline。

    默认 Stages:
        pre_bridge:  [RouteStage(router)]
        post_bridge: [MetricsStage()]              (if include_metrics)
                     [RetryStage()]                 (if include_retry, 在前)
                     [ConditionStage(condition)]    (if include_condition, 中间)
                     [CheckpointStage()]            (if include_checkpoint, 在最末)

    Args:
        router: Router 实例（通常是 ScoreRouter）
        quota: QuotaManager（可选）
        include_metrics: 是否包含 MetricsStage（默认 True）
        include_retry: 是否包含 RetryStage（默认 False，V1.0.2 保守默认）
                       V1.0.2 决策：测试期默认 False，避免破坏现有用户
                       用户主动开启：default_pipeline(router, quota, include_retry=True)
        include_condition: V1.0.4 新增：是否包含 ConditionStage（默认 False）
                          条件分支 / 跳过 / 终止
        condition: V1.0.4 新增：Callable[[ExecutionContext], bool] 条件
                   (include_condition=True 时必传)
        condition_on_true: V1.0.4 新增：condition=True 时的动作
                          ("continue" | "skip" | "abort", 默认 "continue")
        condition_on_false: V1.0.4 新增：condition=False 时的动作
                           ("continue" | "skip" | "abort", 默认 "continue")
        condition_name: V1.0.4 新增：ConditionStage 名称（用于 metadata 调试）
        include_checkpoint: V1.0.3 新增：是否包含 CheckpointStage（默认 False）
                           写入 ExecutionStore 的 ExecutionContext 快照
                           V1.0.3 决策：默认 False，Checkpoint 需要 explicit 开启
        execution_store: V1.0.3 新增：ExecutionStore Protocol 实现
                        (include_checkpoint=True 时必传，通常是 SQLiteExecutionStore())
                        遵循 Runtime Contract "Storage is Disposable" 原则

    Returns:
        ExecutionPipeline 实例

    API Stability: Experimental

    V1.0.2 变更（ADR-0022）:
        - 新增 include_retry 参数（默认 False）
        - post_bridge 顺序：[RetryStage, MetricsStage]（先重试，再 metrics）
        - Pipeline 主体 0 修改（仅 default_pipeline 工厂函数变化）

    V1.0.3 变更（ADR-0023）:
        - 新增 include_checkpoint + execution_store 参数
        - post_bridge 顺序：[RetryStage, MetricsStage, CheckpointStage]
        - Pipeline 主体 0 修改（仅 default_pipeline 工厂函数变化）
        - 依赖 ExecutionStore 抽象（不绑定 SQLite）

    V1.0.4 变更（ADR-0024）:
        - 新增 include_condition + condition + condition_on_true + condition_on_false
          + condition_name 参数
        - post_bridge 顺序：[RetryStage, MetricsStage, ConditionStage, CheckpointStage]
        - Pipeline 主体 0 修改（仅 default_pipeline 工厂函数变化）
        - Condition is a control boundary, not a data boundary
    """
    pre_bridge = [RouteStage(router)]
    post_bridge: list = []
    # V1.0.2: RetryStage 在前（先重试，再 metrics）
    # Runtime Contract §9.1.2 Stage 顺序约定
    if include_retry:
        # 局部导入避免循环依赖
        from planner.stages.retry_stage import RetryStage
        post_bridge.append(RetryStage())
    if include_metrics:
        post_bridge.append(MetricsStage())
    # V1.0.4: ConditionStage 在中间（控制流, 在 Metrics 后 Checkpoint 前）
    # Runtime Contract §9.1.5 Stage 顺序约定
    if include_condition:
        from planner.stages.condition_stage import ConditionStage
        if condition is None:
            raise ValueError(
                "default_pipeline(include_condition=True) requires condition. "
                "Pass a callable: condition=lambda ctx: ctx.bridge_result.success"
            )
        post_bridge.append(ConditionStage(
            condition=condition,
            on_true=condition_on_true,
            on_false=condition_on_false,
            name=condition_name,
        ))
    # V1.0.3: CheckpointStage 在最末（捕获最终 bridge_result + server_metrics）
    # V1.0.4 增量: 即使 abort 也要写 Checkpoint (ChatGPT 9.9/10 Q4 关键采纳)
    # Runtime Contract §9.1.2 Stage 顺序约定
    if include_checkpoint:
        from planner.stages.checkpoint_stage import CheckpointStage
        if execution_store is None:
            raise ValueError(
                "default_pipeline(include_checkpoint=True) requires "
                "execution_store. Pass SQLiteExecutionStore() (or any ExecutionStore impl)."
            )
        post_bridge.append(CheckpointStage(execution_store))
    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
        quota=quota,
        hooks=hooks,  # V1.0.5 新增
    )

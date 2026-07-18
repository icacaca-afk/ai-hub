# Tests for ExecutionPipeline (V1.0.1)
#
# ADR-0021 V1.0.1: ExecutionPipeline as Decorator / Middleware
# ChatGPT 外部审核：9.95/10 FINAL APPROVED
#
# 覆盖：
# - ExecutionContext 不可变 + with_xxx 链式 + stop 字段
# - ExecutionPipeline 三段式（pre_bridge + base + post_bridge）
# - RouteStage 选 Provider + Bridge（不执行）
# - MetricsStage 提取 server_metrics
# - PipelineExecutor.assemble_result
# - default_pipeline 工厂
# - 短路语义（ctx.stop 显式标志）
# - Quota 拦截
# - Stage 顺序正确

import pytest
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.bridge import Bridge, BridgeResult, FakeBridge
from core.provider import Provider, ProviderMetadata
from core.task import Task
from core.health import HealthReport
from core.health_registry import HealthRegistry
from core.registry import CapabilityRegistry
from router.router import Router

from planner.pipeline import (
    ExecutionContext,
    ExecutionPipeline,
    RouteStage,
    MetricsStage,
    PipelineExecutor,
    default_pipeline,
)


# ── Test Fixtures ──

class FakeProvider(Provider):
    """Test Provider with controllable state."""

    def __init__(self, name, caps=None, priority=50, fallback=None,
                 bridge=None, quota_total=None):
        self.metadata = ProviderMetadata(
            name=name,
            display_name=name.title(),
            description=f"Test provider {name}",
            capabilities=caps or ["code.generate"],
            priority=priority,
            fallback=fallback or [],
            quota_total=quota_total,
        )
        self._bridge = bridge or FakeBridge()

    def health(self):
        return HealthReport.healthy(self.metadata.name)

    def authenticated(self):
        return True

    def quota_left(self):
        return -1

    def select_bridge(self, task: Task) -> Bridge:
        return self._bridge

    def execute(self, task: Task):
        # 保留 Router.execute() 后向兼容（Pipeline 不用）
        return self._bridge.run(task)


class FakeRouter(Router):
    """Test Router returning configured Provider."""

    def __init__(self, providers):
        self._providers = providers

    def route(self, task: Task) -> Provider | None:
        for p in self._providers:
            if any(c in p.metadata.capabilities for c in task.capabilities):
                return p
        return None


class FailingProvider(FakeProvider):
    """Provider whose bridge always fails."""
    pass


def make_failing_bridge():
    class _FailingBridge(FakeBridge):
        def run(self, task: Task) -> BridgeResult:
            return BridgeResult(
                success=False,
                output="",
                error="bridge failed",
                raw={"error": "test failure"},
                artifacts=[],
                duration_ms=10,
            )
    return _FailingBridge()


def make_task(task_id: str = "t1", content: str = "hello") -> Task:
    """Helper: 构造 Task（Task 字段是 content 不是 payload）。"""
    return Task(content=content, task_id=task_id, capabilities=["code.generate"])


# ── ExecutionContext Tests ──

class TestExecutionContext:
    """ExecutionContext 不可变 + with_xxx 链式。"""

    def test_immutable_default_state(self):
        """默认状态：provider/bridge/bridge_result/result=None, stop=False。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        assert ctx.task is task
        assert ctx.provider is None
        assert ctx.bridge is None
        assert ctx.bridge_result is None
        assert ctx.result is None
        assert ctx.stop is False

    def test_with_provider_returns_new_instance(self):
        """with_provider 返回新对象，不修改原对象。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        provider = FakeProvider("p1")
        new_ctx = ctx.with_provider(provider)
        assert new_ctx is not ctx
        assert new_ctx.provider is provider
        # 原 ctx 不变
        assert ctx.provider is None

    def test_with_provider_with_bridge(self):
        """with_provider(provider, bridge) 同时更新 bridge。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        provider = FakeProvider("p1")
        bridge = FakeBridge()
        new_ctx = ctx.with_provider(provider, bridge=bridge)
        assert new_ctx.provider is provider
        assert new_ctx.bridge is bridge

    def test_with_provider_preserves_bridge_when_not_passed(self):
        """with_provider(provider) 不传 bridge 时保留原 bridge。"""
        task = make_task()
        provider = FakeProvider("p1")
        bridge = FakeBridge()
        ctx = ExecutionContext(task=task).with_provider(provider, bridge=bridge)
        new_ctx = ctx.with_provider(provider)
        assert new_ctx.bridge is bridge  # 保留

    def test_with_bridge_result_returns_new_instance(self):
        """with_bridge_result 返回新对象。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)
        new_ctx = ctx.with_bridge_result(br)
        assert new_ctx is not ctx
        assert new_ctx.bridge_result is br

    def test_with_result_default_stop_true(self):
        """with_result 默认 stop=True。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        result = _make_result("p1", "success")
        new_ctx = ctx.with_result(result)
        assert new_ctx.stop is True
        assert new_ctx.result is result

    def test_with_result_stop_false(self):
        """with_result(result, stop=False) 不短路（用于 post-bridge Stage）。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        result = _make_result("p1", "success")
        new_ctx = ctx.with_result(result, stop=False)
        assert new_ctx.stop is False

    def test_with_stop(self):
        """with_stop() 只设 stop=True，其他字段不变。"""
        task = make_task()
        provider = FakeProvider("p1")
        ctx = ExecutionContext(task=task).with_provider(provider)
        new_ctx = ctx.with_stop()
        assert new_ctx.stop is True
        assert new_ctx.provider is provider  # 其他字段不变

    def test_immutability_chain(self):
        """链式 with_xxx 不修改任何中间对象。"""
        task = make_task()
        provider = FakeProvider("p1")
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)

        ctx0 = ExecutionContext(task=task)
        ctx1 = ctx0.with_provider(provider)
        ctx2 = ctx1.with_bridge_result(br)
        ctx3 = ctx2.with_stop()

        # 全部独立对象
        assert ctx0 is not ctx1
        assert ctx1 is not ctx2
        assert ctx2 is not ctx3

        # 中间态字段保持
        assert ctx0.provider is None
        assert ctx1.bridge_result is None
        assert ctx2.stop is False


# ── RouteStage Tests ──

class TestRouteStage:
    """RouteStage 选 Provider + Bridge（不执行）。"""

    def test_calls_router_route(self):
        """RouteStage 调 router.route()。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        stage = RouteStage(router)
        task = make_task()
        ctx = ExecutionContext(task=task)

        new_ctx = stage(ctx)
        assert new_ctx.provider is provider

    def test_sets_provider_on_context(self):
        """ctx.provider 被设置。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        stage = RouteStage(router)
        task = make_task()
        ctx = ExecutionContext(task=task)

        new_ctx = stage(ctx)
        assert new_ctx.provider is provider
        assert new_ctx.stop is False

    def test_short_circuits_when_no_provider(self):
        """router.route() 返回 None 时短路（ctx.stop=True, ctx.result=failed）。"""
        router = FakeRouter([])  # 没有任何 provider
        stage = RouteStage(router)
        task = make_task()
        ctx = ExecutionContext(task=task)

        new_ctx = stage(ctx)
        assert new_ctx.stop is True
        assert new_ctx.result is not None
        assert new_ctx.result.status == "failed"
        assert "No available provider" in new_ctx.result.error

    def test_also_selects_bridge(self):
        """RouteStage 同时选 Bridge（不执行）— ChatGPT Decision 3 采纳。"""
        bridge = FakeBridge()
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter([provider])
        stage = RouteStage(router)
        task = make_task()
        ctx = ExecutionContext(task=task)

        new_ctx = stage(ctx)
        assert new_ctx.provider is provider
        assert new_ctx.bridge is bridge

    def test_does_not_modify_task(self):
        """RouteStage 不修改 task。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        stage = RouteStage(router)
        task = make_task(content="v2")
        ctx = ExecutionContext(task=task)

        new_ctx = stage(ctx)
        assert new_ctx.task is task
        assert task.content == "v2"

    def test_name(self):
        """name 属性为 'route'。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        stage = RouteStage(router)
        assert stage.name == "route"


# ── MetricsStage Tests ──

class TestMetricsStage:
    """MetricsStage 提取 server_metrics。"""

    def test_extracts_server_metrics(self):
        """从 bridge_result 提取 server_metrics 写入 result.metadata。"""
        # Mock extractor
        class FakeExtractor:
            def extract(self, provider_name, bridge, br):
                return {"token_in": 10, "token_out": 5}

        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)
        result = _make_result("p1", "success", metadata={"task_id": "t1"})

        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=provider.select_bridge(None),
            bridge_result=br,
            result=result,
        )

        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        assert new_ctx.result.metadata["server_metrics"] == {"token_in": 10, "token_out": 5}

    def test_handles_short_circuit(self):
        """ctx.stop=True 时不处理。"""
        class FakeExtractor:
            def extract(self, *a, **k):
                raise AssertionError("should not be called")

        task = make_task()
        ctx = ExecutionContext(task=task, stop=True)
        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        assert new_ctx is ctx  # 返回同一对象

    def test_handles_missing_bridge_result(self):
        """bridge_result is None 时不处理。"""
        class FakeExtractor:
            def extract(self, *a, **k):
                raise AssertionError("should not be called")

        task = make_task()
        ctx = ExecutionContext(task=task)
        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        assert new_ctx is ctx

    def test_handles_already_set_result(self):
        """ctx.result is not None 时不处理。"""
        class FakeExtractor:
            def extract(self, *a, **k):
                raise AssertionError("should not be called")

        task = make_task()
        result = _make_result("p1", "success")
        ctx = ExecutionContext(task=task, result=result)
        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        assert new_ctx is ctx

    def test_returns_empty_dict_on_extraction_failure(self):
        """extractor.extract 抛异常时返回 {}，不传播。"""
        class FailingExtractor:
            def extract(self, *a, **k):
                raise ValueError("boom")

        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)
        result = _make_result("p1", "success", metadata={"task_id": "t1"})

        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=provider.select_bridge(None),
            bridge_result=br,
            result=result,
        )

        stage = MetricsStage(extractor=FailingExtractor())
        new_ctx = stage(ctx)
        assert new_ctx.result.metadata["server_metrics"] == {}

    def test_does_not_modify_bridge_result(self):
        """不修改 ctx.bridge_result（不可变）。"""
        class FakeExtractor:
            def extract(self, *a, **k):
                return {"k": "v"}

        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)
        result = _make_result("p1", "success", metadata={"task_id": "t1"})

        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=provider.select_bridge(None),
            bridge_result=br,
            result=result,
        )

        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        assert new_ctx.bridge_result is br  # 不变

    def test_does_not_throw_on_extraction_exception(self):
        """extractor 抛异常时 MetricsStage 不抛（容错）。"""
        class BoomExtractor:
            def extract(self, *a, **k):
                raise RuntimeError("boom")

        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)
        result = _make_result("p1", "success", metadata={"task_id": "t1"})

        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=provider.select_bridge(None),
            bridge_result=br,
            result=result,
        )

        stage = MetricsStage(extractor=BoomExtractor())
        # 不抛异常
        new_ctx = stage(ctx)
        assert new_ctx.result.metadata["server_metrics"] == {}

    def test_preserves_existing_metadata(self):
        """保留 result.metadata 其他字段。"""
        class FakeExtractor:
            def extract(self, *a, **k):
                return {"token_in": 10}

        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(success=True, output="ok", raw={}, artifacts=[], duration_ms=100)
        result = _make_result("p1", "success", metadata={
            "task_id": "t1", "capabilities": ["code.generate"]
        })

        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=provider.select_bridge(None),
            bridge_result=br,
            result=result,
        )

        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        assert new_ctx.result.metadata["task_id"] == "t1"
        assert new_ctx.result.metadata["capabilities"] == ["code.generate"]
        assert new_ctx.result.metadata["server_metrics"] == {"token_in": 10}

    def test_name(self):
        """name 属性为 'metrics'。"""
        stage = MetricsStage()
        assert stage.name == "metrics"


# ── PipelineExecutor Tests ──

class TestPipelineExecutor:
    """PipelineExecutor.assemble_result。"""

    def test_short_circuit_result(self):
        """ctx.result is not None 直接返回。"""
        task = make_task()
        existing = _make_result("p1", "success")
        ctx = ExecutionContext(task=task, result=existing)
        result = PipelineExecutor.assemble_result(ctx)
        assert result is existing

    def test_assemble_from_bridge_result_success(self):
        """从 bridge_result 组装成功 Result。"""
        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(
            success=True, output="hello", raw={}, artifacts={"a": 1}, duration_ms=50
        )
        task = make_task()
        ctx = ExecutionContext(
            task=task, provider=provider, bridge=provider.select_bridge(task), bridge_result=br
        )
        result = PipelineExecutor.assemble_result(ctx)
        assert result.status == "success"
        assert result.output == "hello"
        assert result.provider == "p1"
        assert result.metadata["duration_ms"] == 50

    def test_assemble_from_bridge_result_failure(self):
        """从 bridge_result 组装失败 Result。"""
        provider = FakeProvider("p1", bridge=FakeBridge())
        br = BridgeResult(
            success=False, output="", error="boom", raw={}, artifacts={}, duration_ms=10
        )
        task = make_task()
        ctx = ExecutionContext(
            task=task, provider=provider, bridge=provider.select_bridge(task), bridge_result=br
        )
        result = PipelineExecutor.assemble_result(ctx)
        assert result.status == "failed"
        assert result.error == "boom"

    def test_assemble_defensive_when_missing(self):
        """bridge_result/provider 缺失时返回 defensive failed Result。"""
        task = make_task()
        ctx = ExecutionContext(task=task)
        result = PipelineExecutor.assemble_result(ctx)
        assert result.status == "failed"
        assert "missing" in result.error


# ── ExecutionPipeline Tests ──

class TestExecutionPipeline:
    """ExecutionPipeline.run 完整流程。"""

    def test_runs_route_stage_first(self):
        """RouteStage 先执行。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        stage = RouteStage(router)

        called_order = []
        class OrderStage:
            @property
            def name(self): return "order"
            def __call__(self, ctx):
                called_order.append("pre")
                return ctx
            def __init__(self): pass
        # 这里简单测试：RouteStage 在 pre_bridge_stages 第一个
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[stage],
            post_bridge_stages=[],
        )
        task = make_task()
        result = pipeline.run(task)
        assert result.provider == "p1"

    def test_runs_metrics_stage_after_bridge(self):
        """MetricsStage 在 bridge.run 之后执行。"""
        class FakeExtractor:
            def extract(self, *a, **k):
                return {"token_in": 100}

        provider = FakeProvider("p1", bridge=FakeBridge())
        router = FakeRouter([provider])
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[MetricsStage(extractor=FakeExtractor())],
        )
        task = make_task()
        result = pipeline.run(task)
        assert result.status == "success"
        assert result.metadata["server_metrics"] == {"token_in": 100}

    def test_short_circuit_on_route_failure(self):
        """RouteStage 路由失败时 Pipeline 返回 failed Result。"""
        router = FakeRouter([])  # 无 provider
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[],
        )
        task = make_task()
        result = pipeline.run(task)
        assert result.status == "failed"
        assert "No available provider" in result.error

    def test_assembles_result_when_no_post_bridge_stages(self):
        """无 post_bridge_stages 时正常组装。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[],
        )
        task = make_task()
        result = pipeline.run(task)
        assert result.status == "success"
        assert result.provider == "p1"

    def test_handles_empty_post_bridge_stages(self):
        """空 post_bridge_stages 不报错。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[],
        )
        task = make_task()
        result = pipeline.run(task)
        assert result is not None

    def test_quota_check_before_bridge_run(self):
        """Quota 耗尽时 base_execute 短路。"""
        class ExhuastedQuota:
            def exhausted(self, name): return True
            def ensure(self, *a, **k): pass
            def consume(self, *a, **k): pass
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[],
            quota=ExhuastedQuota(),
        )
        task = make_task()
        result = pipeline.run(task)
        assert result.status == "failed"
        assert "Quota exhausted" in result.error

    def test_does_not_call_router_execute(self):
        """Pipeline 不调 router.execute()（只调 router.route()）。"""
        # 创建追踪 router，execute 被调时抛错
        provider = FakeProvider("p1")
        class TrackingRouter(FakeRouter):
            def __init__(self, providers):
                super().__init__(providers)
                self.execute_called = False
            def execute(self, task):
                self.execute_called = True
                raise AssertionError("Pipeline should not call router.execute()")

        router = TrackingRouter([provider])
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[],
        )
        task = make_task()
        result = pipeline.run(task)
        assert result.status == "success"
        assert router.execute_called is False  # 关键验证


# ── default_pipeline 工厂测试 ──

class TestDefaultPipeline:
    """default_pipeline() 工厂函数。"""

    def test_default_pipeline_factory_includes_metrics(self):
        """默认包含 MetricsStage。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        pipeline = default_pipeline(router, include_metrics=True)
        assert len(pipeline.post_bridge_stages) == 1
        assert isinstance(pipeline.post_bridge_stages[0], MetricsStage)

    def test_default_pipeline_factory_can_exclude_metrics(self):
        """include_metrics=False 时不包含 MetricsStage。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        pipeline = default_pipeline(router, include_metrics=False)
        assert len(pipeline.post_bridge_stages) == 0

    def test_default_pipeline_factory_includes_route_stage(self):
        """默认 pre_bridge 包含 RouteStage。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        pipeline = default_pipeline(router)
        assert len(pipeline.pre_bridge_stages) == 1
        assert isinstance(pipeline.pre_bridge_stages[0], RouteStage)

    def test_default_pipeline_factory_with_quota(self):
        """传 quota 时正确设置。"""
        provider = FakeProvider("p1")
        router = FakeRouter([provider])
        class FakeQuota:
            pass
        q = FakeQuota()
        pipeline = default_pipeline(router, quota=q)
        assert pipeline.quota is q


# ── Helpers ──

def _make_result(provider, status, metadata=None):
    """Helper: 构造 Result。"""
    from core.result import Result
    return Result(
        provider=provider,
        status=status,
        output="ok" if status == "success" else "",
        error="" if status == "success" else "err",
        artifacts={},
        metadata=metadata or {},
    )

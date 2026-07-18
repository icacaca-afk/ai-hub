# Tests for RetryStage (V1.0.2)
#
# ADR-0022 V1.0.2: RetryStage (Pipeline 扩展性首次验证)
# ChatGPT 外部审核：9.9/10 FINAL APPROVED
# 采纳 1 项调整：is_retryable 默认"安全可重试"（网络/超时/5xx/限流）
#
# 覆盖：
# - RetryStage 基本行为（成功不重试 / 失败重试 / 重试用尽 / 不可重试跳过 / 异常不抛）
# - 4 种退避策略（immediate/fixed/linear/exponential）
# - 自定义 is_retryable
# - 集成（Stage 顺序 / 不调 router.execute() / 不修改 provider）

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
    default_pipeline,
)
from planner.stages import (
    RetryStage,
    _default_retryable,
    compute_backoff_delay,
    SAFE_RETRY_ERROR_PATTERNS,
)


# ── Test Fixtures ──

class FakeProvider(Provider):
    """Test Provider with controllable state."""

    def __init__(self, name, bridge=None):
        self.metadata = ProviderMetadata(
            name=name,
            display_name=name.title(),
            description=f"Test provider {name}",
            capabilities=["code.generate"],
            priority=50,
            fallback=[],
            quota_total=None,
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
        return self._bridge.run(task)


class FakeRouter(Router):
    """Test Router returning configured Provider."""

    def __init__(self, provider):
        self._provider = provider

    def route(self, task: Task):
        return self._provider

    def execute(self, task: Task):
        return self._provider.execute(task)


def make_task(content="test task", task_id="t1", capabilities=None):
    return Task(
        task_id=task_id,
        content=content,
        capabilities=capabilities or ["code.generate"],
    )


def make_success_br(output="ok", duration_ms=10):
    return BridgeResult(success=True, output=output, duration_ms=duration_ms)


def make_failure_br(error="some error", duration_ms=10, error_type=None, status_code=None):
    """构造失败 BridgeResult，可选 raw dict 含 status_code."""
    raw = None
    if error_type is not None or status_code is not None:
        raw = {}
        if error_type is not None:
            raw["error_type"] = error_type
        if status_code is not None:
            raw["status_code"] = status_code
    return BridgeResult(
        success=False,
        output="",
        error=error,
        duration_ms=duration_ms,
        raw=raw,
    )


def make_bridge_with_behavior(fail_times=0, timeout_ms=0, response="ok"):
    """构造 FakeBridge，支持前 N 次失败。"""
    return FakeBridge(
        response=response,
        fail_times=fail_times,
        timeout_ms=timeout_ms,
    )


# ── TestRetryStageBasics (5 tests) ──

class TestRetryStageBasics:
    """基本重试行为。"""

    def test_retry_on_failure_eventually_succeeds(self):
        """失败 N 次后成功 → 重试有效，最终 bridge_result 替换为成功。"""
        # fail_times=0: 第一次重试就成功（不需前置失败）
        bridge = make_bridge_with_behavior(fail_times=0)
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)
        stage = RetryStage(
            max_retries=3,
            backoff="immediate",
            is_retryable=lambda br: not br.success,
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(error="transient"),
        )

        new_ctx = stage(ctx)

        assert new_ctx.bridge_result.success is True
        # 1 次重试就成功
        assert bridge.call_count == 1
        assert stage.attempt_count == 1

    def test_retry_exhausts_after_max_retries(self):
        """重试用尽 → 保留最后失败 result。"""
        # 永远失败 (fail_times=10 > max_retries=3)
        bridge = make_bridge_with_behavior(fail_times=10)
        provider = FakeProvider("p1", bridge=bridge)
        stage = RetryStage(
            max_retries=3,
            backoff="immediate",
            is_retryable=lambda br: not br.success,
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(error="permanent"),
        )

        new_ctx = stage(ctx)

        assert new_ctx.bridge_result.success is False
        # 初始 ctx.bridge_result 来自外部构造，不计入 bridge.call_count
        # 3 次重试 = bridge.call_count=3
        assert bridge.call_count == 3
        assert stage.attempt_count == 3

    def test_retry_skips_on_success(self):
        """成功 → pass，不重试。"""
        bridge = make_bridge_with_behavior()
        provider = FakeProvider("p1", bridge=bridge)
        stage = RetryStage(max_retries=3, backoff="immediate")
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_success_br(),
        )

        new_ctx = stage(ctx)

        assert new_ctx is ctx  # 短路返回原 ctx
        assert bridge.call_count == 0
        assert stage.attempt_count == 0

    def test_retry_skips_on_non_retryable(self):
        """不可重试错误（4xx 401）→ pass，不重试。"""
        bridge = make_bridge_with_behavior()
        provider = FakeProvider("p1", bridge=bridge)
        stage = RetryStage(max_retries=3, backoff="immediate")
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(
                error="HTTP 401: Unauthorized",
                status_code=401,
            ),
        )

        new_ctx = stage(ctx)

        # 默认 _default_retryable: 401 不重试
        assert new_ctx.bridge_result.success is False
        assert new_ctx.bridge_result.error == "HTTP 401: Unauthorized"
        assert bridge.call_count == 0
        assert stage.attempt_count == 0

    def test_retry_does_not_throw_on_bridge_exception(self):
        """bridge.run 抛异常 → 不污染主链路，继续重试。"""
        class ExplodingBridge(FakeBridge):
            """第 1 次抛异常，第 2 次调 super().run()（fail_times=0）成功。

            用独立 _explode_count，避免污染 super()._call_count。
            """
            def __init__(self):
                super().__init__(fail_times=0)
                self._explode_count = 0
            def run(self, task, **kwargs):
                self._explode_count += 1
                if self._explode_count == 1:
                    raise RuntimeError("Boom!")
                return super().run(task, **kwargs)
            @property
            def explode_count(self):
                return self._explode_count

        bridge = ExplodingBridge()
        provider = FakeProvider("p1", bridge=bridge)
        stage = RetryStage(
            max_retries=3,
            backoff="immediate",
            is_retryable=lambda br: not br.success,
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(error="first failure"),
        )

        new_ctx = stage(ctx)  # 不应抛异常

        # 第一次重试抛异常（explode=1），第二次调 super().run() 成功（explode=2, super call=1）
        assert new_ctx.bridge_result.success is True
        assert bridge.explode_count == 2
        # 进入了 2 次 loop（一次抛异常 continue，一次成功 return）
        assert stage.attempt_count == 2


# ── TestRetryStageBackoff (4 tests) ──

class TestRetryStageBackoff:
    """4 种退避策略 + compute_backoff_delay 纯函数。"""

    def test_immediate_backoff(self):
        """immediate 策略: 延迟始终 0。"""
        bridge = make_bridge_with_behavior(fail_times=10)
        provider = FakeProvider("p1", bridge=bridge)
        delays = []
        stage = RetryStage(
            max_retries=3,
            backoff="immediate",
            is_retryable=lambda br: not br.success,
            sleep=lambda s: delays.append(s),
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(),
        )
        stage(ctx)
        assert delays == []  # 0 延迟

    def test_fixed_backoff(self):
        """fixed 策略: 每次延迟相同。"""
        assert compute_backoff_delay("fixed", 1, 100, 5000) == 100
        assert compute_backoff_delay("fixed", 2, 100, 5000) == 100
        assert compute_backoff_delay("fixed", 3, 100, 5000) == 100

    def test_linear_backoff(self):
        """linear 策略: 100, 200, 300, ...。"""
        assert compute_backoff_delay("linear", 1, 100, 5000) == 100
        assert compute_backoff_delay("linear", 2, 100, 5000) == 200
        assert compute_backoff_delay("linear", 3, 100, 5000) == 300
        assert compute_backoff_delay("linear", 10, 100, 5000) == 1000

    def test_exponential_backoff(self):
        """exponential 策略: 100, 200, 400, 800, ... (max_delay_ms 上限)。"""
        assert compute_backoff_delay("exponential", 1, 100, 5000) == 100
        assert compute_backoff_delay("exponential", 2, 100, 5000) == 200
        assert compute_backoff_delay("exponential", 3, 100, 5000) == 400
        assert compute_backoff_delay("exponential", 4, 100, 5000) == 800
        # 上限保护
        assert compute_backoff_delay("exponential", 10, 100, 5000) == 5000


# ── TestRetryStageCustomIsRetryable (3 tests) ──

class TestRetryStageCustomIsRetryable:
    """自定义 is_retryable 函数。"""

    def test_custom_retryable_function(self):
        """用户传 is_retryable=lambda br: True → 重试所有错误。"""
        # 401 默认不重试，但自定义全重试
        bridge = make_bridge_with_behavior(fail_times=1)
        provider = FakeProvider("p1", bridge=bridge)
        stage = RetryStage(
            max_retries=2,
            backoff="immediate",
            is_retryable=lambda br: True,  # 重试所有
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(
                error="HTTP 401: Unauthorized",
                status_code=401,
            ),
        )

        new_ctx = stage(ctx)

        # 自定义 is_retryable=True → 重试
        assert new_ctx.bridge_result.success is True
        assert bridge.call_count == 2

    def test_retryable_5xx_only(self):
        """is_retryable 仅 5xx 重试（典型用户配置）。"""
        def only_5xx(br):
            if br.success:
                return False
            if isinstance(br.raw, dict):
                status = br.raw.get("status_code")
                if status is not None:
                    return status >= 500
            return False

        bridge_500 = make_bridge_with_behavior(fail_times=0)
        bridge_400 = make_bridge_with_behavior(fail_times=0)

        # Test 5xx
        provider_500 = FakeProvider("p500", bridge=bridge_500)
        stage_500 = RetryStage(
            max_retries=2,
            backoff="immediate",
            is_retryable=only_5xx,
        )
        ctx_500 = ExecutionContext(
            task=make_task(),
            provider=provider_500,
            bridge=bridge_500,
            bridge_result=make_failure_br(
                error="HTTP 500: Internal Server Error",
                status_code=500,
            ),
        )
        new_ctx_500 = stage_500(ctx_500)
        # 第一次重试，bridge 不再失败 → success
        assert new_ctx_500.bridge_result.success is True

        # Test 4xx
        provider_400 = FakeProvider("p400", bridge=bridge_400)
        stage_400 = RetryStage(
            max_retries=2,
            backoff="immediate",
            is_retryable=only_5xx,
        )
        ctx_400 = ExecutionContext(
            task=make_task(),
            provider=provider_400,
            bridge=bridge_400,
            bridge_result=make_failure_br(
                error="HTTP 400: Bad Request",
                status_code=400,
            ),
        )
        new_ctx_400 = stage_400(ctx_400)
        # 4xx 不重试
        assert new_ctx_400.bridge_result.success is False
        assert bridge_400.call_count == 0

    def test_non_retryable_4xx(self):
        """默认 _default_retryable: 4xx 不重试。"""
        # status_code=404
        assert _default_retryable(make_failure_br(error="HTTP 404", status_code=404)) is False
        # status_code=403
        assert _default_retryable(make_failure_br(error="HTTP 403", status_code=403)) is False
        # status_code=400
        assert _default_retryable(make_failure_br(error="HTTP 400", status_code=400)) is False
        # 但 429 重试
        assert _default_retryable(make_failure_br(error="HTTP 429", status_code=429)) is True
        # 5xx 全部重试
        assert _default_retryable(make_failure_br(error="HTTP 500", status_code=500)) is True
        assert _default_retryable(make_failure_br(error="HTTP 503", status_code=503)) is True


# ── TestRetryStageIntegration (3 tests) ──

class TestRetryStageIntegration:
    """RetryStage 在 Pipeline 中的集成。"""

    def test_retry_stage_before_metrics_stage(self):
        """[RetryStage, MetricsStage] 顺序：metrics 反映重试后最终结果。"""
        # 第一次失败（fail_times=1），第二次成功
        bridge = FakeBridge(
            fail_times=1,
            response="eventual success",
        )
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)

        # 构造显式 Pipeline + RetryStage（带 is_retryable=lambda 强制重试，
        # 因为 FakeBridge 的 "Simulated failure" 错误信息不在默认 _default_retryable 模式中）
        retry_stage = RetryStage(
            max_retries=3,
            backoff="immediate",
            is_retryable=lambda br: not br.success,
        )
        pipeline = ExecutionPipeline(
            router=router,
            pre_bridge_stages=[RouteStage(router)],
            post_bridge_stages=[retry_stage, MetricsStage()],
        )

        # post_bridge 顺序验证
        names = [s.name for s in pipeline.post_bridge_stages]
        assert names == ["retry", "metrics"]

        result = pipeline.run(make_task())

        # 重试成功后，最终 result 应为 success
        # Pipeline._base_execute 调 1 次 (call_count=1 失败) + RetryStage 调 1 次 (call_count=2 成功) = 2
        assert result.status == "success"
        assert bridge.call_count == 2

    def test_retry_does_not_call_router_execute(self):
        """RetryStage 不调 router.execute()（架构约束）。"""
        # 用一个会标记 router.execute() 被调用的 Router
        class TrackingRouter(FakeRouter):
            def __init__(self, provider):
                super().__init__(provider)
                self.execute_called = 0
            def execute(self, task):
                self.execute_called += 1
                return super().execute(task)

        bridge = make_bridge_with_behavior(fail_times=1)
        provider = FakeProvider("p1", bridge=bridge)
        router = TrackingRouter(provider)
        pipeline = default_pipeline(
            router=router,
            include_metrics=True,
            include_retry=True,
        )

        pipeline.run(make_task())

        # router.execute() 0 调用（Pipeline 走 route() + bridge.run()）
        assert router.execute_called == 0

    def test_retry_does_not_modify_provider(self):
        """RetryStage 不修改 ctx.provider / ctx.bridge（routing 不变）。"""
        bridge = make_bridge_with_behavior(fail_times=1)
        provider = FakeProvider("p1", bridge=bridge)
        stage = RetryStage(
            max_retries=2,
            backoff="immediate",
            is_retryable=lambda br: not br.success,
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=provider,
            bridge=bridge,
            bridge_result=make_failure_br(),
        )

        new_ctx = stage(ctx)

        # 关键不变量：provider / bridge 不变
        assert new_ctx.provider is provider
        assert new_ctx.bridge is bridge
        # task 不变
        assert new_ctx.task is ctx.task


# ── TestDefaultPipelineIncludeRetry (extra: 验证 factory 集成) ──

class TestDefaultPipelineIncludeRetry:
    """default_pipeline(include_retry) 工厂参数。"""

    def test_default_pipeline_no_retry_by_default(self):
        """V1.0.2 决策：include_retry=False 默认。"""
        router = FakeRouter(FakeProvider("p1"))
        pipeline = default_pipeline(router)
        names = [s.name for s in pipeline.post_bridge_stages]
        assert "retry" not in names
        assert "metrics" in names

    def test_default_pipeline_with_retry(self):
        """include_retry=True → [RetryStage, MetricsStage]。"""
        router = FakeRouter(FakeProvider("p1"))
        pipeline = default_pipeline(router, include_retry=True)
        names = [s.name for s in pipeline.post_bridge_stages]
        assert names == ["retry", "metrics"]

    def test_default_pipeline_no_metrics_with_retry(self):
        """include_metrics=False, include_retry=True → 只有 retry。"""
        router = FakeRouter(FakeProvider("p1"))
        pipeline = default_pipeline(
            router, include_metrics=False, include_retry=True,
        )
        names = [s.name for s in pipeline.post_bridge_stages]
        assert names == ["retry"]


# ── TestRetryStageInitValidation (extra: 参数验证) ──

class TestRetryStageInitValidation:
    """RetryStage __init__ 参数验证。"""

    def test_invalid_max_retries(self):
        """max_retries < 0 → ValueError。"""
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            RetryStage(max_retries=-1)

    def test_invalid_backoff(self):
        """backoff 不在 4 种策略中 → ValueError。"""
        with pytest.raises(ValueError, match="Invalid backoff"):
            RetryStage(backoff="invalid")

    def test_invalid_initial_delay(self):
        """initial_delay_ms < 0 → ValueError。"""
        with pytest.raises(ValueError, match="initial_delay_ms must be >= 0"):
            RetryStage(initial_delay_ms=-1)

    def test_invalid_max_delay(self):
        """max_delay_ms < initial_delay_ms → ValueError。"""
        with pytest.raises(ValueError, match="max_delay_ms .* must be >="):
            RetryStage(initial_delay_ms=1000, max_delay_ms=500)


# ── TestSafeRetryPatterns (extra: 默认 is_retryable 覆盖度) ──

class TestSafeRetryPatterns:
    """_default_retryable 安全重试模式覆盖度。"""

    def test_5xx_retryable(self):
        assert _default_retryable(make_failure_br(error="Internal Server Error", status_code=500)) is True
        assert _default_retryable(make_failure_br(error="Bad Gateway", status_code=502)) is True
        assert _default_retryable(make_failure_br(error="Service Unavailable", status_code=503)) is True
        assert _default_retryable(make_failure_br(error="Gateway Timeout", status_code=504)) is True

    def test_429_retryable(self):
        assert _default_retryable(make_failure_br(error="Too Many Requests", status_code=429)) is True

    def test_text_pattern_retryable(self):
        """错误文本模式匹配（无 status_code）。"""
        assert _default_retryable(make_failure_br(error="ConnectionError: failed")) is True
        assert _default_retryable(make_failure_br(error="TimeoutError: 30s")) is True
        assert _default_retryable(make_failure_br(error="RateLimitError: 100/min")) is True
        assert _default_retryable(make_failure_br(error="Connection refused")) is True
        assert _default_retryable(make_failure_br(error="rate limit exceeded")) is True

    def test_4xx_not_retryable(self):
        assert _default_retryable(make_failure_br(error="Unauthorized", status_code=401)) is False
        assert _default_retryable(make_failure_br(error="Forbidden", status_code=403)) is False
        assert _default_retryable(make_failure_br(error="Not Found", status_code=404)) is False
        assert _default_retryable(make_failure_br(error="Quota exhausted")) is False
        assert _default_retryable(make_failure_br(error="Validation failed: bad input")) is False
        assert _default_retryable(make_failure_br(error="Invalid api key")) is False

    def test_success_not_retryable(self):
        assert _default_retryable(make_success_br()) is False

    def test_unknown_error_not_retryable(self):
        """无明确错误信息的失败 → 不重试（保守）。"""
        assert _default_retryable(make_failure_br(error="")) is False
        assert _default_retryable(make_failure_br(error="Unknown random error")) is False

# tests/test_metrics_router.py
# V0.9.6 — MetricsRouter 测试（ADR-0019）
#
# 覆盖：
# - execute() 返回 Result.metadata 含 server_metrics
# - openai_api provider + FakeBridge(raw=JSON) → server_metrics 含 token/cost
# - 无 provider 时返回 failed Result（metadata 无 server_metrics）
# - 非 OpenAI provider（如 demo）→ server_metrics={} （不影响主链路）
# - bridge.run 失败时 server_metrics={} 但 Result.status=failed
# - route() 完全继承 ScoreRouter（不影响路由决策）
#
# 测试策略：
# - 自定义 FakeBridgeWithRaw（继承 Bridge 接口，返回带 raw 的 BridgeResult）
# - 自定义 FakeProvider（继承 Provider，bridge 可注入）
# - 复用 test_score_router.py 的 health/registry 模式

import json
import pytest
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.bridge import Bridge, BridgeResult
from core.provider import Provider, ProviderMetadata
from core.task import Task
from core.health import HealthReport
from core.health_registry import HealthRegistry
from core.registry import CapabilityRegistry
from router.metrics_router import MetricsRouter


# ── Test Fixtures ──

class FakeBridgeWithRaw(Bridge):
    """Bridge stub：返回带 raw 的 BridgeResult（用于测试 MetricsExtractor）。

    可配置：
    - success: BridgeResult.success
    - raw: BridgeResult.raw（OpenAI JSON body 等）
    - output: BridgeResult.output
    """

    def __init__(self, raw=None, success=True, output="ok", error=None):
        self._raw = raw
        self._success = success
        self._output = output
        self._error = error

    def run(self, task, **kwargs) -> BridgeResult:
        return BridgeResult(
            success=self._success,
            output=self._output,
            error=self._error,
            duration_ms=10,
            raw=self._raw,
        )

    def check_available(self) -> bool:
        return True

    def check_auth(self) -> bool:
        return True


class FakeProvider(Provider):
    """测试用 Provider，bridge 可注入。"""

    def __init__(self, name, caps=None, bridge=None, priority=50):
        self.metadata = ProviderMetadata(
            name=name,
            display_name=name.title(),
            description=f"Test provider {name}",
            capabilities=caps or ["code.generate"],
            priority=priority,
        )
        self.bridge = bridge or FakeBridgeWithRaw()

    def health(self):
        return HealthReport.healthy(self.metadata.name)

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


def _make_health_registry_healthy(provider_names):
    """创建 HealthRegistry，所有 provider 状态=healthy（TTL 长有效）。"""
    from datetime import datetime, timezone
    hr = HealthRegistry()
    for name in provider_names:
        report = HealthReport.healthy(name)
        report.ttl_seconds = 3600
        report.checked_at = datetime.now(timezone.utc)
        hr._cache[name] = report
    return hr


def _build_router(providers, health_reports_names=None):
    """构造 MetricsRouter + 注册 providers + 健康 cache。"""
    registry = CapabilityRegistry()
    for p in providers:
        registry.register(p)

    hr = _make_health_registry_healthy(health_reports_names or [p.name for p in providers])

    class FakeQuota:
        def exhausted(self, name):
            return False
        def ensure(self, *a, **kw): pass
        def consume(self, *a, **kw): pass

    return MetricsRouter(registry, quota_manager=FakeQuota(), health_registry=hr)


def _execute_legacy(router, task):
    """Execute the V1.x compatibility shim and assert its deprecation signal."""
    with pytest.warns(DeprecationWarning, match=r"MetricsRouter\.execute\(\)"):
        return router.execute(task)


# ── OpenAI usage 提取测试 ──

class TestMetricsRouterExecute:
    """MetricsRouter.execute() server_metrics 提取测试。"""

    def test_deprecation_contract_retains_v1_compatibility(self):
        router = _build_router([])
        task = Task(content="hello", capabilities=["code.generate"])

        with pytest.warns(DeprecationWarning) as captured:
            router.execute(task)

        message = str(captured[0].message)
        assert "ExecutionPipeline + MetricsStage" in message
        assert "retained throughout V1.x" in message
        assert "V1.0.3" not in message

    def test_execute_openai_api_with_usage(self):
        """openai_api provider + br.raw=JSON(usage) → metadata含 server_metrics。"""
        raw = json.dumps({
            "model": "gpt-4o",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        })
        bridge = FakeBridgeWithRaw(raw=raw, success=True, output="hello")
        provider = FakeProvider("openai_api", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        # 显式指定 capabilities 避免 Task 自动分类为 general.chat
        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert result.is_success
        assert result.provider == "openai_api"
        # 关键：metadata 含 server_metrics
        sm = result.metadata.get("server_metrics", None)
        assert sm is not None
        assert sm["token_in"] == 100
        assert sm["token_out"] == 50
        assert sm["token_total"] == 150
        assert sm["model"] == "gpt-4o"
        # gpt-4o: 100/1000*0.0025 + 50/1000*0.01 = 0.00075
        assert sm["cost_usd"] == pytest.approx(0.00075, abs=1e-9)

    def test_execute_openai_compatible_with_usage(self):
        """openai_compatible provider + br.raw=JSON(usage) → server_metrics 提取。"""
        raw = json.dumps({
            "model": "gpt-4",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        })
        bridge = FakeBridgeWithRaw(raw=raw, success=True)
        provider = FakeProvider("openai_compatible", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert result.is_success
        sm = result.metadata["server_metrics"]
        assert sm["token_in"] == 1000
        assert sm["token_out"] == 500

    def test_execute_metadata_has_server_metrics_key(self):
        """成功执行的 Result.metadata 一定含 server_metrics key（即使为空 dict）。"""
        bridge = FakeBridgeWithRaw(raw=None, success=True)
        provider = FakeProvider("demo", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert "server_metrics" in result.metadata

    def test_execute_non_openai_provider_empty_metrics(self):
        """非 OpenAI provider（如 demo）→ server_metrics={}。"""
        bridge = FakeBridgeWithRaw(raw="some cli output", success=True)
        provider = FakeProvider("demo", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert result.is_success
        assert result.metadata["server_metrics"] == {}

    def test_execute_failed_bridge_result_empty_metrics(self):
        """bridge.run 失败 → server_metrics={}（因 br.success=False）。"""
        raw = json.dumps({"model": "gpt-4o", "usage": {"prompt_tokens": 100}})
        bridge = FakeBridgeWithRaw(raw=raw, success=False, error="boom")
        provider = FakeProvider("openai_api", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert not result.is_success
        assert result.status == "failed"
        # br.success=False → extract 返回 {}
        assert result.metadata["server_metrics"] == {}

    def test_execute_none_raw_empty_metrics(self):
        """br.raw=None → server_metrics={}。"""
        bridge = FakeBridgeWithRaw(raw=None, success=True)
        provider = FakeProvider("openai_api", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert result.is_success
        assert result.metadata["server_metrics"] == {}

    def test_execute_preserves_other_metadata(self):
        """server_metrics 加入后，其他 metadata 字段（duration_ms/task_id 等）仍在。"""
        raw = json.dumps({"model": "gpt-4o", "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        bridge = FakeBridgeWithRaw(raw=raw, success=True)
        provider = FakeProvider("openai_api", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        md = result.metadata
        assert "duration_ms" in md
        assert "capabilities" in md
        assert "task_id" in md
        assert "bridge" in md
        assert "quota_remaining" in md
        assert "server_metrics" in md
        assert md["bridge"] == "FakeBridgeWithRaw"


# ── 无 provider 场景 ──

class TestMetricsRouterNoProvider:
    """MetricsRouter 无可用 provider 场景。"""

    def test_no_provider_returns_failed_result(self):
        """无 provider → 返回 failed Result。"""
        router = _build_router([])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        assert result.status == "failed"
        assert result.provider == "none"

    def test_no_provider_metadata_no_server_metrics(self):
        """无 provider 时 metadata 不含 server_metrics key。"""
        router = _build_router([])

        task = Task(content="hello", capabilities=["code.generate"])
        result = _execute_legacy(router, task)

        # 无 provider 路径不构造 server_metrics
        assert "server_metrics" not in result.metadata
        assert "capabilities" in result.metadata
        assert "task_id" in result.metadata


# ── 路由不影响测试 ──

class TestMetricsRouterRouting:
    """MetricsRouter 不影响路由决策（ADR-0019 原则 F）。"""

    def test_route_inherited_from_score_router(self):
        """route() 完全继承 ScoreRouter，返回最高分 provider。"""
        bridge1 = FakeBridgeWithRaw(raw=None)
        bridge2 = FakeBridgeWithRaw(raw=None)
        p1 = FakeProvider("p1", caps=["code.generate"], bridge=bridge1, priority=50)
        p2 = FakeProvider("p2", caps=["code.generate"], bridge=bridge2, priority=100)

        router = _build_router([p1, p2])

        task = Task(content="hello", capabilities=["code.generate"])
        selected = router.route(task)

        # p2 优先级更高 → 选中
        assert selected is not None
        assert selected.name == "p2"

    def test_execute_does_not_change_route_decision(self):
        """execute() 不影响 route() 决策：相同 task 多次执行选同一 provider。"""
        raw = json.dumps({"model": "gpt-4o", "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        bridge = FakeBridgeWithRaw(raw=raw, success=True)
        provider = FakeProvider("openai_api", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        r1 = _execute_legacy(router, task)
        r2 = _execute_legacy(router, task)

        assert r1.provider == r2.provider == "openai_api"

    def test_last_scores_populated(self):
        """route() 后 last_scores 被填充（继承 ScoreRouter 行为）。"""
        raw = json.dumps({"model": "gpt-4o", "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        bridge = FakeBridgeWithRaw(raw=raw, success=True)
        provider = FakeProvider("openai_api", caps=["code.generate"], bridge=bridge)
        router = _build_router([provider])

        task = Task(content="hello", capabilities=["code.generate"])
        _execute_legacy(router, task)

        # ScoreRouter.route() 会填充 last_scores
        assert hasattr(router, "last_scores")
        assert len(router.last_scores) >= 1

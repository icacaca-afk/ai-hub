# Tests for ScoreRouter (V0.8.0)
#
# 覆盖：
# - Score 计算正确性
# - Health 过滤 + Score 排序
# - Quota 过滤
# - Fallback 链
# - last_scores / last_route_reason
# - ProviderScore dataclass

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
from router.score_router import ScoreRouter, ProviderScore, HEALTH_SCORES


# ── Test Fixtures ──

class FakeProvider(Provider):
    """Test Provider with controllable health state."""

    def __init__(self, name, caps=None, priority=50, fallback=None):
        self.metadata = ProviderMetadata(
            name=name,
            display_name=name.title(),
            description=f"Test provider {name}",
            capabilities=caps or ["code.generate"],
            priority=priority,
            fallback=fallback or [],
        )
        self.bridge = FakeBridge()

    def health(self):
        return HealthReport.healthy(self.metadata.name)

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


def make_provider(name, caps, priority=50, fallback=None):
    """Create a test FakeProvider."""
    return FakeProvider(name, caps, priority, fallback)


def make_health_registry(reports):
    """Create a HealthRegistry with pre-populated cache."""
    from datetime import datetime, timezone
    hr = HealthRegistry()
    for name, report in reports.items():
        report.ttl_seconds = 3600
        report.checked_at = datetime.now(timezone.utc)
        hr._cache[name] = report
    return hr


def make_health_report(status="healthy", latency_ms=None, message=""):
    """Create a HealthReport for testing."""
    return HealthReport(
        provider="test",
        status=status,
        authenticated=True if status != "unavailable" else False,
        quota_ok=True,
        latency_ms=latency_ms,
        message=message,
    )


class TestProviderScore:
    """ProviderScore dataclass 测试。"""

    def test_total_calculation_all_100(self):
        """所有维度 100 分，总分 100。"""
        s = ProviderScore(
            provider_name="test",
            capability_score=100,
            health_score=100,
            priority_score=100,
            latency_score=100,
            quota_score=100,
        )
        assert s.total == 100.0

    def test_total_calculation_mixed(self):
        """混合分数计算。"""
        s = ProviderScore(
            provider_name="test",
            capability_score=100,
            health_score=100,
            priority_score=50,
            latency_score=50,
            quota_score=100,
        )
        # (100*40 + 100*25 + 50*20 + 50*10 + 100*5) / 100 = 85.0
        assert s.total == 85.0

    def test_total_zero(self):
        """所有维度 0 分，总分 0。"""
        s = ProviderScore(provider_name="test")
        assert s.total == 0.0

    def test_to_dict(self):
        """to_dict 包含所有字段。"""
        s = ProviderScore(provider_name="test", capability_score=80)
        d = s.to_dict()
        assert "provider" in d
        assert "capability" in d
        assert "health" in d
        assert "priority" in d
        assert "latency" in d
        assert "quota" in d
        assert "total" in d

    def test_health_scores_mapping(self):
        """HEALTH_SCORES 映射正确。"""
        assert HEALTH_SCORES["healthy"] == 100.0
        assert HEALTH_SCORES["unknown"] == 60.0
        assert HEALTH_SCORES["degraded"] == 30.0
        assert HEALTH_SCORES["unavailable"] == 0.0


class TestScoreRouterRouting:
    """ScoreRouter 路由测试。"""

    def _setup_router(self, providers, health_reports=None, quota_exhausted_names=None):
        """Helper: 构建带 mock 的 ScoreRouter。"""
        registry = CapabilityRegistry()
        for p in providers:
            registry.register(p)

        hr = make_health_registry(health_reports or {})

        class FakeQuota:
            def exhausted(self, name):
                return name in (quota_exhausted_names or [])
            def ensure(self, *a, **kw): pass
            def consume(self, *a, **kw): pass

        router = ScoreRouter(registry, quota_manager=FakeQuota(), health_registry=hr)
        return router

    def test_highest_score_selected(self):
        """分数最高的 Provider 被选中。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)
        p2 = make_provider("p2", ["code.generate"], priority=50)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("healthy", latency_ms=500),
                "p2": make_health_report("healthy", latency_ms=500),
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        assert selected is not None
        assert selected.name == "p1"  # higher priority → higher score

    def test_health_affects_score(self):
        """healthy 的 Provider 分数高于 degraded。"""
        p1 = make_provider("p1", ["code.generate"], priority=50)
        p2 = make_provider("p2", ["code.generate"], priority=100)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("healthy"),
                "p2": make_health_report("degraded", message="slow"),
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        # p1: health=100, priority=50/100=50
        # p2: health=30, priority=100/100=100
        # p1 score = (100*40 + 100*25 + 50*20 + 50*10 + 100*5) / 100 = 80
        # p2 score = (100*40 + 30*25 + 100*20 + 50*10 + 100*5) / 100 = 67.5
        assert selected.name == "p1"

    def test_latency_affects_score(self):
        """低延迟的 Provider 分数更高。"""
        p1 = make_provider("p1", ["code.generate"], priority=50)
        p2 = make_provider("p2", ["code.generate"], priority=50)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("healthy", latency_ms=500),   # ≤1s → 100
                "p2": make_health_report("healthy", latency_ms=5000),  # 5s → 50
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        assert selected.name == "p1"

    def test_unavailable_skipped(self):
        """unavailable 的 Provider 被跳过。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)
        p2 = make_provider("p2", ["code.generate"], priority=10)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("unavailable", message="down"),
                "p2": make_health_report("healthy"),
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        assert selected.name == "p2"
        assert "p1" in str(router.last_route_reason["skipped"])

    def test_quota_exhausted_skipped(self):
        """额度耗尽的 Provider 被跳过。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)
        p2 = make_provider("p2", ["code.generate"], priority=10)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("healthy"),
                "p2": make_health_report("healthy"),
            },
            quota_exhausted_names=["p1"]
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        assert selected.name == "p2"
        assert "p1" in str(router.last_route_reason["skipped"])

    def test_all_unavailable_returns_none(self):
        """所有 Provider unavailable 返回 None。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)

        router = self._setup_router(
            [p1],
            health_reports={
                "p1": make_health_report("unavailable", message="down"),
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        assert selected is None
        assert router.last_route_reason["selected"] is None

    def test_last_scores_populated(self):
        """路由后 last_scores 被填充。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)
        p2 = make_provider("p2", ["code.generate"], priority=50)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("healthy"),
                "p2": make_health_report("healthy"),
            }
        )
        task = Task.from_text("write code")
        router.route(task)

        assert len(router.last_scores) == 2
        assert router.last_scores[0].total >= router.last_scores[1].total

    def test_last_route_reason_has_score(self):
        """last_route_reason 包含 score 字段。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)

        router = self._setup_router(
            [p1],
            health_reports={"p1": make_health_report("healthy")}
        )
        task = Task.from_text("write code")
        router.route(task)

        assert "score" in router.last_route_reason
        assert router.last_route_reason["strategy"] == "score"

    def test_fallback_chain_works(self):
        """所有候选不可用时走 fallback 链。"""
        p1 = make_provider("p1", ["code.generate"], priority=100, fallback=["p2"])
        p2 = make_provider("p2", ["code.review"], priority=50)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("unavailable", message="down"),
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        # p1 unavailable → fallback to p2
        assert selected is not None
        assert selected.name == "p2"
        assert router.last_route_reason["strategy"] == "fallback"

    def test_execute_inherited(self):
        """execute() 继承自父类，正常工作。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)

        router = self._setup_router(
            [p1],
            health_reports={"p1": make_health_report("healthy")}
        )
        task = Task.from_text("write code")
        result = router.execute(task)

        assert result.is_success
        assert result.provider == "p1"

    def test_unknown_treated_as_available(self):
        """unknown health 的 Provider 参与评分。"""
        p1 = make_provider("p1", ["code.generate"], priority=100)

        router = self._setup_router([p1])  # 无 health report → unknown
        task = Task.from_text("write code")
        selected = router.route(task)

        assert selected is not None
        assert selected.name == "p1"

    def test_equal_scores_first_wins(self):
        """分数相同时，排在前面的优先（stable sort）。"""
        p1 = make_provider("p1", ["code.generate"], priority=50)
        p2 = make_provider("p2", ["code.generate"], priority=50)

        router = self._setup_router(
            [p1, p2],
            health_reports={
                "p1": make_health_report("healthy", latency_ms=500),
                "p2": make_health_report("healthy", latency_ms=500),
            }
        )
        task = Task.from_text("write code")
        selected = router.route(task)

        # 完全相同分数，p1 先注册 → p1 选中
        assert selected.name == "p1"

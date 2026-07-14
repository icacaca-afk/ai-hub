# tests/test_health_router.py
# V0.7 HealthAwareRouter tests

"""HealthAwareRouter routing tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.bridge import FakeBridge
from core.health import HealthReport
from core.provider import Provider, ProviderMetadata
from core.registry import CapabilityRegistry
from core.task import Task
from core.health_registry import HealthRegistry
from router.health_router import HealthAwareRouter


class FakeProvider(Provider):
    """Test Provider with controllable health state."""

    def __init__(self, name, caps=None, priority=50):
        self.metadata = ProviderMetadata(
            name=name, display_name=name, description="test",
            capabilities=caps or ["code.generate"], priority=priority,
        )
        self.bridge = FakeBridge()

    def health(self):
        return HealthReport.healthy(self.metadata.name)

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


def make_health_registry(reports):
    """Create a HealthRegistry with pre-populated cache (no real health() calls)."""
    from datetime import datetime, timezone
    hr = HealthRegistry()
    for name, report in reports.items():
        report.ttl_seconds = 3600
        report.checked_at = datetime.now(timezone.utc)
        hr._cache[name] = report
    return hr


class TestHealthAwareRouter:
    """HealthAwareRouter core tests."""

    def setup_method(self):
        self.registry = CapabilityRegistry()

    def _make_router(self, providers, health_reports=None):
        for p in providers:
            self.registry.register(p)
        hr = make_health_registry(health_reports or {})
        return HealthAwareRouter(self.registry, health_registry=hr)

    # -- Basic routing --

    def test_healthy_provider_selected(self):
        p = FakeProvider("p1", ["code.generate"], priority=50)
        router = self._make_router([p], {"p1": HealthReport.healthy("p1")})
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result is not None
        assert result.name == "p1"

    def test_unavailable_provider_skipped(self):
        p1 = FakeProvider("p1", ["code.generate"], priority=100)
        p2 = FakeProvider("p2", ["code.generate"], priority=50)
        router = self._make_router([p1, p2], {
            "p1": HealthReport.unavailable("p1", "down"),
            "p2": HealthReport.healthy("p2"),
        })
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result is not None
        assert result.name == "p2"

    def test_degraded_goes_to_fallback_group(self):
        p_degraded = FakeProvider("degraded", ["code.generate"], priority=100)
        p_healthy = FakeProvider("healthy", ["code.generate"], priority=50)
        router = self._make_router([p_degraded, p_healthy], {
            "degraded": HealthReport("degraded", status="degraded", message="slow"),
            "healthy": HealthReport.healthy("healthy"),
        })
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result is not None
        assert result.name == "healthy"

    def test_degraded_selected_if_no_healthy(self):
        p = FakeProvider("p1", ["code.generate"], priority=50)
        router = self._make_router([p], {
            "p1": HealthReport("p1", status="degraded", message="slow"),
        })
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result is not None
        assert result.name == "p1"

    def test_unknown_treated_as_available(self):
        p = FakeProvider("p1", ["code.generate"], priority=50)
        router = self._make_router([p], {"p1": HealthReport.unknown("p1")})
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result is not None
        assert result.name == "p1"

    def test_all_unavailable_returns_none(self):
        p1 = FakeProvider("p1", ["code.generate"], priority=50)
        router = self._make_router([p1], {
            "p1": HealthReport.unavailable("p1", "down"),
        })
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result is None

    def test_last_route_reason_recorded(self):
        p1 = FakeProvider("p1", ["code.generate"], priority=50)
        router = self._make_router([p1], {"p1": HealthReport.healthy("p1")})
        task = Task.from_text("write some code")
        router.route(task)
        assert router.last_route_reason.get("selected") == "p1"
        assert router.last_route_reason.get("group") == "healthy"

    def test_last_route_reason_records_skipped(self):
        p1 = FakeProvider("p1", ["code.generate"], priority=100)
        p2 = FakeProvider("p2", ["code.generate"], priority=50)
        router = self._make_router([p1, p2], {
            "p1": HealthReport.unavailable("p1", "down"),
            "p2": HealthReport.healthy("p2"),
        })
        task = Task.from_text("write some code")
        router.route(task)
        skipped = router.last_route_reason.get("skipped", [])
        assert any("p1" in s for s in skipped)

    # -- execute inherited --

    def test_execute_inherited(self):
        p = FakeProvider("p1", ["code.generate"], priority=50)
        router = self._make_router([p], {"p1": HealthReport.healthy("p1")})
        task = Task.from_text("write some code")
        result = router.execute(task)
        assert result.status == "success"
        assert result.provider == "p1"

    # -- Priority preserved --

    def test_priority_preserved_within_healthy_group(self):
        p_low = FakeProvider("low", ["code.generate"], priority=10)
        p_high = FakeProvider("high", ["code.generate"], priority=100)
        router = self._make_router([p_low, p_high], {
            "low": HealthReport.healthy("low"),
            "high": HealthReport.healthy("high"),
        })
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result.name == "high"

    def test_fallback_chain_works(self):
        p1 = FakeProvider("p1", ["code.generate"], priority=50)
        p1.metadata.fallback = ["demo"]
        demo = FakeProvider("demo", ["code.generate"], priority=1)
        router = self._make_router([p1, demo], {
            "p1": HealthReport.unavailable("p1", "down"),
            "demo": HealthReport.healthy("demo"),
        })
        task = Task.from_text("write some code")
        result = router.route(task)
        assert result.name == "demo"
